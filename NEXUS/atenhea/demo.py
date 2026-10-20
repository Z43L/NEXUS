from pathlib import Path
from tempfile import TemporaryDirectory

from nra_runtime import initial_state, load_nram, save_nram, try_commit


with TemporaryDirectory() as tmp:
    path = Path(tmp) / "distilgpt2-nra-demo.nram"
    save_nram(path, initial_state())
    result = try_commit(path, [(1, 2), (2, 4)], [(3, 6), (4, 8)])
    state = load_nram(path)
    print(f"Target model: {state['model']['target_model']} ({state['model']['target_model_params']:,} params)")
    print(f"Test backend: {state['model']['backend']}")
    print(f"Mutation accepted: {result['accepted']}")
    print(f"Validation MSE: {result['before']:.4f} -> {result['after']:.4f}")
    print(f"Saved version: {state['version']}; delta: {state['model']['delta_weight']:.4f}")
