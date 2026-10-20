// SSD -> shared Apple Silicon memory -> GPU consumption. No model downloads.
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#include <algorithm>
#include <atomic>
#include <barrier>
#include <chrono>
#include <condition_variable>
#include <cstdio>
#include <cstring>
#include <fcntl.h>
#include <random>
#include <stdexcept>
#include <string>
#include <sys/stat.h>
#include <thread>
#include <unistd.h>
#include <vector>

using Clock = std::chrono::steady_clock;
static double ms(Clock::time_point t) { return std::chrono::duration<double,std::milli>(Clock::now()-t).count(); }
static void check(bool ok, const std::string& message) { if (!ok) throw std::runtime_error(message); }
static bool read_all(int fd, void* dst, size_t size, uint64_t offset) {
    auto* p = (char*)dst;
    while (size) {
        auto n = pread(fd,p,size,(off_t)offset);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) return false;
        size -= n; p += n; offset += n;
    }
    return true;
}
struct Entry { uint64_t offset, bytes; };
struct ReaderPool {
    int fd; std::barrier<> begin, end; std::atomic<int> next{0}; std::atomic<bool> good{true}; bool stop=false;
    const std::vector<Entry>* jobs=nullptr; char* dst=nullptr; size_t stride=0;
    std::vector<std::thread> workers;
    ReaderPool(int f,int n): fd(f),begin(n+1),end(n+1) {
        for(int i=0;i<n;++i) workers.emplace_back([this] {
            for(;;) {
                begin.arrive_and_wait(); if(stop) return;
                for(int j;(j=next++)<(int)jobs->size();)
                    if(!read_all(fd,dst+j*stride,(*jobs)[j].bytes,(*jobs)[j].offset)) good=false;
                end.arrive_and_wait();
            }
        });
    }
    void read(const std::vector<Entry>& input,void* output,size_t spacing) {
        jobs=&input;dst=(char*)output;stride=spacing;next=0;good=true;
        begin.arrive_and_wait();end.arrive_and_wait();check(good,"pread failed");
    }
    ~ReaderPool(){stop=true;begin.arrive_and_wait();for(auto& t:workers)t.join();}
};
int main(int argc,char** argv) { @autoreleasepool { try {
    check(argc>=2,"usage: ssd-metal-bench FILE.experts [batches=16] [rounds=3]");
    int batches=argc>2?std::stoi(argv[2]):16, rounds=argc>3?std::stoi(argv[3]):3;
    check(batches>0&&rounds>0,"positive batches and rounds required");
    const int width=10;
    const bool disjoint=argc>4 && std::string(argv[4])=="disjoint";
    int fd=open(argv[1],O_RDONLY);check(fd>=0,"cannot open experts file");
    fcntl(fd,F_NOCACHE,1);fcntl(fd,F_RDAHEAD,0);
    uint8_t header[64]; check(read_all(fd,header,64,0),"short header");
    check(!memcmp(header,"STRX",4),"not a Strata expert file");
    uint32_t version,nl,ne;memcpy(&version,header+4,4);memcpy(&nl,header+8,4);memcpy(&ne,header+12,4);
    check(version==1&&nl>0&&nl<=256&&ne>0&&ne<=4096,"invalid expert header");
    std::vector<uint64_t> table(nl*4);check(read_all(fd,table.data(),table.size()*8,64),"short table");
    struct stat st{};fstat(fd,&st);
    size_t max_bytes=0;
    for(unsigned l=0;l<nl;++l){
        uint64_t size=table[l*4+1]+table[l*4+2]+table[l*4+3];
        check(size>0&&size%4==0&&table[l*4]+size*ne<=(uint64_t)st.st_size,"bad expert extent");
        max_bytes=std::max(max_bytes,(size_t)size);
    }
    size_t stride=(max_bytes+16383)/16384*16384;
    id<MTLDevice> device=MTLCreateSystemDefaultDevice();check(device!=nil,"Metal unavailable");
    check(device.hasUnifiedMemory,"requires unified memory");
    id<MTLBuffer> buffer=[device newBufferWithLength:stride*width options:MTLResourceStorageModeShared];
    id<MTLBuffer> sums=[device newBufferWithLength:4*width options:MTLResourceStorageModeShared];
    id<MTLBuffer> lengths=[device newBufferWithLength:4*width options:MTLResourceStorageModeShared];
    check(buffer&&sums&&lengths,"shared allocation failed");
    NSError* error=nil;
    NSString* source=@"#include <metal_stdlib>\nusing namespace metal; kernel void consume(device const uint* data [[buffer(0)]],device uint* out [[buffer(1)]],constant uint* counts [[buffer(2)]],constant uint& stride [[buffer(3)]],uint tid [[thread_index_in_threadgroup]],uint group [[threadgroup_position_in_grid]]) { threadgroup uint scratch[256]; uint sum=0; for(uint i=tid;i<counts[group];i+=256) sum+=data[group*stride+i]; scratch[tid]=sum; threadgroup_barrier(mem_flags::mem_threadgroup); for(uint s=128;s>0;s>>=1){if(tid<s)scratch[tid]+=scratch[tid+s];threadgroup_barrier(mem_flags::mem_threadgroup);}if(tid==0)out[group]=scratch[0]; }";
    id<MTLLibrary> library=[device newLibraryWithSource:source options:nil error:&error];
    check(library!=nil,error?error.description.UTF8String:"compile failed");
    id<MTLComputePipelineState> pipeline=[device newComputePipelineStateWithFunction:[library newFunctionWithName:@"consume"] error:&error];
    check(pipeline!=nil,"pipeline failed");id<MTLCommandQueue> gpu=[device newCommandQueue];
    MTLIOCommandQueueDescriptor* desc=[MTLIOCommandQueueDescriptor new];desc.type=MTLIOCommandQueueTypeConcurrent;desc.priority=MTLIOPriorityNormal;
    id<MTLIOCommandQueue> io=[device newIOCommandQueueWithDescriptor:desc error:&error];
    check(io!=nil,error?error.description.UTF8String:"Metal IO unsupported");
    id<MTLIOFileHandle> handle=[device newIOFileHandleWithURL:[NSURL fileURLWithPath:@(argv[1])] error:&error];
    check(handle!=nil,"Metal IO file handle failed");
    std::mt19937 random(20261016);std::vector<std::vector<Entry>> trace;
    for(int b=0;b<batches;++b){unsigned l=random()%nl;std::vector<Entry> jobs;
        for(int i=0;i<width;++i){unsigned e=random()%ne;uint64_t size=table[l*4+1]+table[l*4+2]+table[l*4+3];jobs.push_back({table[l*4]+e*size,size});}trace.push_back(jobs);}
    std::vector<std::vector<uint32_t>> expected(batches);
    const int modes[]={1,4,6,8,0};
    fprintf(stderr,"device=%s shared_bytes=%zu random_experts=%d batches=%d rounds=%d; pread F_NOCACHE, Metal IO cache policy is driver-managed\n",device.name.UTF8String,stride*width,width,batches,rounds);
    for(int r=0;r<rounds;++r)for(int order=0;order<5;++order){@autoreleasepool{
        int threads=modes[(order+r)%5];
        if(disjoint) {
            std::mt19937 fresh(20261016+r*1009+threads*71+order*13);
            for(auto& jobs:trace){unsigned l=fresh()%nl;for(auto& job:jobs){unsigned e=fresh()%ne;uint64_t size=table[l*4+1]+table[l*4+2]+table[l*4+3];job={table[l*4]+e*size,size};}}
            expected.assign(batches,{});
        }
        ReaderPool pool(fd,threads?threads:1);
        double read_ms=0,gpu_ms=0,kernel_ms=0;uint64_t bytes=0;std::vector<double> latency;
        for(int b=0;b<batches;++b){@autoreleasepool{
            const auto& jobs=trace[b];auto started=Clock::now();
            if(threads)pool.read(jobs,buffer.contents,stride);
            else {
                id<MTLIOCommandBuffer> cb=[io commandBuffer];
                for(int i=0;i<width;++i)[cb loadBuffer:buffer offset:i*stride size:jobs[i].bytes sourceHandle:handle sourceHandleOffset:jobs[i].offset];
                [cb commit];[cb waitUntilCompleted];check(cb.status==MTLIOStatusComplete,"Metal IO failed");
            }
            double read_time=ms(started);read_ms+=read_time;latency.push_back(read_time);
            for(int i=0;i<width;++i){((uint32_t*)lengths.contents)[i]=(uint32_t)(jobs[i].bytes/4);bytes+=jobs[i].bytes;}
            started=Clock::now();id<MTLCommandBuffer> cb=[gpu commandBuffer];id<MTLComputeCommandEncoder> encoder=[cb computeCommandEncoder];
            [encoder setComputePipelineState:pipeline];[encoder setBuffer:buffer offset:0 atIndex:0];[encoder setBuffer:sums offset:0 atIndex:1];[encoder setBuffer:lengths offset:0 atIndex:2];
            uint32_t sw=(uint32_t)(stride/4);[encoder setBytes:&sw length:4 atIndex:3];[encoder dispatchThreadgroups:MTLSizeMake(width,1,1) threadsPerThreadgroup:MTLSizeMake(256,1,1)];[encoder endEncoding];[cb commit];[cb waitUntilCompleted];
            check(cb.status==MTLCommandBufferStatusCompleted,"GPU consumer failed");gpu_ms+=ms(started);kernel_ms+=(cb.GPUEndTime-cb.GPUStartTime)*1000;
            if(expected[b].empty()) {
                for(int i=0;i<width;++i){uint32_t ref=0;const uint32_t* words=(uint32_t*)((char*)buffer.contents+i*stride);for(size_t k=0;k<jobs[i].bytes/4;++k)ref+=words[k];check(ref==((uint32_t*)sums.contents)[i],"CPU/GPU checksum mismatch");}
                expected[b].assign((uint32_t*)sums.contents,(uint32_t*)sums.contents+width);
            }else check(!memcmp(expected[b].data(),sums.contents,width*4),"backend checksum mismatch");
        }}
        std::sort(latency.begin(),latency.end());
        printf("{\"backend\":\"%s\",\"threads\":%d,\"round\":%d,\"bytes\":%llu,\"read_ms\":%.3f,\"consume_gpu_ms\":%.3f,\"kernel_gpu_ms\":%.3f,\"gb_s\":%.4f,\"batch_p50_ms\":%.3f,\"batch_p95_ms\":%.3f,\"verified\":true,\"trace\":\"%s\"}\n",threads?"pread":"metal_io",threads,r,(unsigned long long)bytes,read_ms,gpu_ms,kernel_ms,bytes/read_ms/1e6,latency[latency.size()/2],latency[(latency.size()-1)*95/100],disjoint?"disjoint":"repeated");fflush(stdout);
    }}
    close(fd);return 0;
} catch(const std::exception& e){fprintf(stderr,"error: %s\n",e.what());return 1;} }}
