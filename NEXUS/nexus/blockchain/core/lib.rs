#![cfg_attr(not(feature = "std"), no_std)]

use frame_support::{
    decl_error, decl_event, decl_module, decl_storage,
    dispatch::DispatchResult,
    traits::Get,
};
use frame_system::ensure_signed;
use sp_std::vec::Vec;
use codec::{Encode, Decode};
use sp_runtime::traits::{Hash, Zero};
use sp_core::H256;

/// Estructura para almacenar actualizaciones de conocimiento
#[derive(Encode, Decode, Clone, PartialEq, Debug)]
pub struct KnowledgeUpdate<T: Config> {
    pub knowledge_hash: H256,
    pub knowledge_type: KnowledgeType,
    pub submitter: T::AccountId,
    pub validation_count: u32,
    pub confidence_score: u8,
    pub timestamp: T::BlockNumber,
    pub metadata: Vec<u8>,
}

/// Tipos de conocimiento soportados
#[derive(Encode, Decode, Clone, PartialEq, Debug)]
pub enum KnowledgeType {
    FactualClaim,
    StatisticalData,
    LogicalInference,
    ExperientialMemory,
    PredictiveModel,
}

pub trait Config: frame_system::Config {
    type Event: From<Event<Self>> + Into<<Self as frame_system::Config>::Event>;
    type MinimumValidations: Get<u32>;
    type KnowledgeHash: Hash<Output = H256>;
}

decl_storage! {
    trait Store for Module<T: Config> as KnowledgeLedger {
        /// Almacenamiento principal de actualizaciones de conocimiento
        pub KnowledgeUpdates get(fn knowledge_updates): 
            map hasher(blake2_128_concat) H256 => KnowledgeUpdate<T>;
        
        /// Índice de actualizaciones por validador
        pub ValidatorUpdates get(fn validator_updates):
            double_map hasher(blake2_128_concat) T::AccountId, hasher(blake2_128_concat) H256 => bool;
        
        /// Estadísticas de integridad del conocimiento
        pub IntegrityStats get(fn integrity_stats):
            map hasher(blake2_128_concat) H256 => IntegrityStatistics;
    }
}

decl_event! {
    pub enum Event<T> where <T as frame_system::Config>::AccountId {
        KnowledgeUpdateRegistered(AccountId, H256, KnowledgeType),
        ValidationRecorded(AccountId, H256, bool),
        KnowledgeIntegrityVerified(H256, bool),
        UpdateReverted(H256, AccountId),
    }
}

decl_error! {
    pub enum Error for Module<T: Config> {
        UpdateAlreadyExists,
        InsufficientValidations,
        InvalidKnowledgeHash,
        UpdateNotFound,
    }
}