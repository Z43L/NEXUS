// Exercise the exact no-copy arena buffer path used by the streaming engine.
#include "mtl_rt.h"
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <stdexcept>
#include <sys/mman.h>
#include <unistd.h>
#include <vector>
static void check(bool ok,const char* text){if(!ok)throw std::runtime_error(text);}
int main(){try{
    char path[]="/tmp/ongram-metal-io-XXXXXX";
    int fd=mkstemp(path);check(fd>=0,"temp file");
    std::vector<unsigned char> bytes(65536);
    for(size_t i=0;i<bytes.size();++i)bytes[i]=(unsigned char)((i*73+i/256)%251);
    check(write(fd,bytes.data(),bytes.size())==(ssize_t)bytes.size(),"file write");close(fd);
    mtl::Context context;std::string error;
    void* memory=mmap(nullptr,65536,PROT_READ|PROT_WRITE,MAP_ANON|MAP_PRIVATE,-1,0);
    check(memory!=MAP_FAILED,"mmap");
    memset(memory,0xA5,65536);
    auto arena=context.wrap(memory,65536);
    check(!context.read_io({{&arena,0,0,4096}},error),"uninitialized reader accepted");
    check(context.open_io_file(path,error),error.c_str());
    check(!context.read_io({{&arena,65530,0,4096}},error),"out-of-bounds destination accepted");
    check(context.read_io({{&arena,16384,4096,8192},{&arena,32768,24576,4096}},error),error.c_str());
    auto* actual=(unsigned char*)memory;
    for(size_t i=0;i<65536;++i){unsigned char expected=0xA5;
        if(i>=16384&&i<24576)expected=bytes[i-16384+4096];
        if(i>=32768&&i<36864)expected=bytes[i-32768+24576];
        check(actual[i]==expected,"copied bytes or arena guards differ");}
    context.free(arena);munmap(memory,65536);unlink(path);
    puts("PASS: shared no-copy arena, multiple offsets, byte equality, guard bytes, initialization and bounds");
    return 0;
}catch(const std::exception& e){fprintf(stderr,"FAIL: %s\n",e.what());return 1;}}
