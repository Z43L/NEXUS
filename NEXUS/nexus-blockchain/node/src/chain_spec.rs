use sc_chain_spec::{ChainSpecExtension, ChainSpecGroup};
use serde::{Deserialize, Serialize};
use sp_core::{Pair, Public, sr25519};
use nexus_runtime::{
    AccountId, NexusConfig, Signature, EXISTENTIAL_DEPOSIT,
    opaque::Block, GenesisConfig
};

/// Configuración especializada para la red NEXUS
pub fn nexus_testnet_config() -> Result<ChainSpec, String> {
    let wasm_binary = include_bytes!("../../runtime/wasm/target/wasm32-unknown-unknown/release/nexus_runtime.wasm");
    
    Ok(ChainSpec::from_genesis(
        "Nexus Testnet",
        "nexus_testnet",
        ChainType::Live,
        move || testnet_genesis(
            wasm_binary,
            vec![
                authority_keys_from_seed("Alice"),
                authority_keys_from_seed("Bob"),
            ],
            vec![
                authority_keys_from_seed("Alice"),
                authority_keys_from_seed("Bob"),
                authority_keys_from_seed("Charlie"),
            ],
            get_initial_knowledge_validators(),
        ),
        vec![],
        None,
        None,
        None,
        Some(properties()),
        None,
    ))
}