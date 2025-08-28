#![cfg_attr(not(feature = "std"), no_std)]

pub use sp_runtime::{
    generic, create_runtime_str, impl_opaque_hash, MultiAddress, MultiSignature,
    ApplyExtrinsicResult, transaction_validity::TransactionValidity, Permill,
};
use sp_runtime::traits::{
    BlakeTwo256, IdentifyAccount, Verify, NumberFor, Saturating, OpaqueKeys,
};
use sp_api::impl_runtime_apis;
use sp_consensus_aura::sr25519::AuthorityId as AuraId;
use sp_finality_grandpa::AuthorityId as GrandpaId;
use sp_version::RuntimeVersion;

#[derive(RuntimeDebug)]
pub struct NexusRuntime;

impl frame_system::Config for NexusRuntime {
    type BaseCallFilter = frame_support::traits::Everything;
    type BlockWeights = ();
    type BlockLength = ();
    type DbWeight = ();
    type RuntimeOrigin = RuntimeOrigin;
    type RuntimeCall = RuntimeCall;
    type Nonce = u32;
    type Hash = H256;
    type Hashing = BlakeTwo256;
    type AccountId = <<Signature as Verify>::Signer as IdentifyAccount>::AccountId;
    type Lookup = IdentityLookup<Self::AccountId>;
    type Block = Block;
    type RuntimeEvent = RuntimeEvent;
    type BlockHashCount = BlockHashCount;
    type Version = ();
    type PalletInfo = PalletInfo;
    type AccountData = pallet_balances::AccountData<Balance>;
    type OnNewAccount = ();
    type OnKilledAccount = ();
    type SystemWeightInfo = ();
    type SS58Prefix = ();
    type OnSetCode = ();
    type MaxConsumers = frame_support::traits::ConstU32<16>;
}

impl pallet_nexus_knowledge::Config for Runtime {
    type RuntimeEvent = RuntimeEvent;
    type KnowledgeUpdate = NexusKnowledgeUpdate;
    type ValidatorSet = pallet_nexus_knowledge::ValidatorSet<Self>;
    type WeightInfo = ();
}

pub type Signature = MultiSignature;
pub type BlockNumber = u32;
pub type Balance = u128;
pub type Header = generic::Header<BlockNumber, BlakeTwo256>;
pub type Block = generic::Block<Header, UncheckedExtrinsic>;
pub type UncheckedExtrinsic = generic::UncheckedExtrinsic<Address, RuntimeCall, Signature, SignedExtra>;

#[sp_version::runtime_version]
pub const VERSION: RuntimeVersion = RuntimeVersion {
    spec_name: create_runtime_str!("nexus"),
    impl_name: create_runtime_str!("nexus"),
    authoring_version: 1,
    spec_version: 1,
    impl_version: 1,
    apis: RUNTIME_API_VERSIONS,
    transaction_version: 1,
    state_version: 1,
};