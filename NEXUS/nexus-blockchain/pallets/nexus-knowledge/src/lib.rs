#![cfg_attr(not(feature = "std"), no_std)]

use frame_support::{
    decl_error, decl_event, decl_module, decl_storage,
    dispatch::DispatchResult,
    traits::Get,
};
use frame_system::ensure_signed;
use sp_std::vec::Vec;

pub trait Config: frame_system::Config {
    type RuntimeEvent: From<Event<Self>> + Into<<Self as frame_system::Config>::RuntimeEvent>;
    type KnowledgeUpdate: Parameter + Member + MaybeSerializeDeserialize;
    type ValidatorSet: ValidatorSet<Self::AccountId>;
}

decl_storage! {
    trait Store for Module<T: Config> as NexusKnowledge {
        pub PendingUpdates get(fn pending_updates): 
            map hasher(blake2_128_concat) T::Hash => KnowledgeUpdate<T>;
        
        pub UpdateVotes get(fn update_votes):
            double_map hasher(blake2_128_concat) T::Hash, hasher(blake2_128_concat) T::AccountId => bool;
        
        pub ValidatorReputation get(fn validator_reputation):
            map hasher(blake2_128_concat) T::AccountId => u32;
    }
}

decl_event! {
    pub enum Event<T> where <T as frame_system::Config>::AccountId {
        KnowledgeUpdateProposed(T::AccountId, T::Hash),
        ValidatorVoted(T::AccountId, T::Hash, bool),
        KnowledgeUpdateAccepted(T::Hash),
        KnowledgeUpdateRejected(T::Hash),
    }
}

decl_error! {
    pub enum Error for Module<T: Config> {
        UpdateAlreadyProposed,
        AlreadyVoted,
        UpdateNotFound,
    }
}

decl_module! {
    pub struct Module<T: Config> for enum Call where origin: T::RuntimeOrigin {
        type Error = Error<T>;
        
        fn deposit_event() = default;
        
        #[weight = 10_000]
        pub fn propose_knowledge_update(
            origin,
            update: T::KnowledgeUpdate,
            update_hash: T::Hash
        ) -> DispatchResult {
            let who = ensure_signed(origin)?;
            
            ensure!(!PendingUpdates::<T>::contains_key(update_hash), Error::<T>::UpdateAlreadyProposed);
            
            PendingUpdates::<T>::insert(update_hash, update);
            
            Self::deposit_event(RawEvent::KnowledgeUpdateProposed(who, update_hash));
            
            Ok(())
        }
        
        #[weight = 10_000]
        pub fn vote_on_update(
            origin,
            update_hash: T::Hash,
            approval: bool
        ) -> DispatchResult {
            let who = ensure_signed(origin)?;
            
            ensure!(T::ValidatorSet::is_validator(&who), "No es un validador");
            ensure!(PendingUpdates::<T>::contains_key(update_hash), Error::<T>::UpdateNotFound);
            ensure!(!UpdateVotes::<T>::contains_key(update_hash, &who), Error::<T>::AlreadyVoted);
            
            UpdateVotes::<T>::insert(update_hash, &who, approval);
            
            Self::deposit_event(RawEvent::ValidatorVoted(who, update_hash, approval));
            
            Self::check_consensus(update_hash);
            
            Ok(())
        }
        
        fn check_consensus(update_hash: T::Hash) {
            let validators = T::ValidatorSet::validators();
            let mut approve_count = 0;
            let mut total_votes = 0;
            
            for validator in validators {
                if let Some(vote) = UpdateVotes::<T>::get(update_hash, &validator) {
                    total_votes += 1;
                    if vote {
                        approve_count += 1;
                    }
                }
            }
            
            if total_votes > 0 && (approve_count * 100) / total_votes >= 70 {
                Self::deposit_event(RawEvent::KnowledgeUpdateAccepted(update_hash));
                Self::update_reputation(update_hash, true);
                PendingUpdates::<T>::remove(update_hash);
                
            } else if total_votes == validators.len() {
                Self::deposit_event(RawEvent::KnowledgeUpdateRejected(update_hash));
                Self::update_reputation(update_hash, false);
                PendingUpdates::<T>::remove(update_hash);
            }
        }
    }
}