#!/usr/bin/env python3
"""
Ingest Hugging Face datasets into CHL .memory database.

Usage:
  # Ingest first 100 rows of wikitext:
  python scripts/ingest_hf.py --dataset wikitext --config wikitext-2-raw-v1 --limit 100

  # Ingest custom dataset into a specific memory file:
  python scripts/ingest_hf.py --dataset username/dataset-name --text-column content --memory custom.memory
"""

import os
import sys
import json
import argparse
from pathlib import Path

def check_dependencies():
    try:
        import datasets
    except ImportError:
        print("❌ Error: The 'datasets' library is required to run this script.")
        print("Please install it using: pip install datasets huggingface_hub")
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description="Ingest Hugging Face datasets into CHL .memory")
    parser.add_argument("--dataset", type=str, required=True, help="Hugging Face dataset name (e.g. 'wikitext')")
    parser.add_argument("--config", type=str, default=None, help="Dataset configuration/subset name (optional)")
    parser.add_argument("--split", type=str, default="train", help="Dataset split (default: 'train')")
    parser.add_argument("--text-column", type=str, default="text", help="Column name to use as memory text")
    parser.add_argument("--memory", type=str, default=None, help="Target .memory file path")
    parser.add_argument("--limit", type=int, default=500, help="Maximum number of items to ingest (default: 500)")
    
    args = parser.parse_args()
    
    check_dependencies()
    from datasets import load_dataset

    # Resolve memory file path
    memory_path_str = args.memory
    if not memory_path_str:
        memory_path_str = os.environ.get("CHL_PERSIST_PATH")
        if not memory_path_str:
            memory_path_str = str(Path(__file__).resolve().parent.parent / "chl-memory-data" / "chl-memory.memory")
            
    memory_path = Path(memory_path_str)
    
    # Ensure it ends with .memory
    if not memory_path.name.endswith(".memory"):
        memory_path = memory_path.with_name(f"{memory_path.stem}.memory")
        
    print(f"[CHL] Target memory file: {memory_path}")
    print(f"[CHL] Fetching dataset '{args.dataset}' (split: '{args.split}', config: '{args.config}')...")
    
    try:
        if args.config:
            ds = load_dataset(args.dataset, name=args.config, split=args.split)
        else:
            ds = load_dataset(args.dataset, split=args.split)
    except Exception as e:
        print(f"❌ Error loading dataset from Hugging Face: {e}")
        sys.exit(1)
        
    print(f"✅ Dataset loaded. Total items available: {len(ds)}")
    
    # Parse text columns
    text_columns = [col.strip() for col in args.text_column.split(",") if col.strip()]
    if not text_columns:
        print("❌ Error: Please specify at least one valid column with --text-column")
        sys.exit(1)

    # Verify all text columns exist
    first_row = ds[0] if len(ds) > 0 else {}
    missing_cols = [col for col in text_columns if col not in first_row]
    if missing_cols:
        available_cols = list(first_row.keys())
        print(f"❌ Error: Text column(s) {missing_cols} not found in dataset schema.")
        print(f"   Available columns: {available_cols}")
        print("   Please specify valid columns with --text-column")
        sys.exit(1)
        
    # Create parent directory if needed
    memory_path.parent.mkdir(parents=True, exist_ok=True)
    
    print(f"[CHL] Ingesting up to {args.limit} records...")
    
    ingested_count = 0
    with open(memory_path, "a", encoding="utf-8") as f:
        for idx, row in enumerate(ds):
            if ingested_count >= args.limit:
                break
                
            if len(text_columns) > 1:
                text_parts = []
                for col in text_columns:
                    val = str(row.get(col, "")).strip()
                    if val:
                        text_parts.append(f"{col}: {val}")
                text = "\n\n".join(text_parts)
            else:
                text = str(row.get(text_columns[0], "")).strip()
                
            # Skip empty entries
            if not text or len(text) < 5:
                continue
                
            # Construct payload with all other columns
            payload = {k: v for k, v in row.items() if k not in text_columns}
            
            # Construct standard metadata
            metadata = {
                "source": "huggingface",
                "dataset": args.dataset,
                "split": args.split,
                "row_index": idx,
                "quality": 8
            }
            
            # Format event as a standard remember mutation
            event = {
                "type": "remember",
                "text": text,
                "payload": payload,
                "metadata": metadata
            }
            
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
            ingested_count += 1
            
            if ingested_count % 100 == 0:
                print(f"   Ingested {ingested_count}/{args.limit}...")
                
    print(f"🎉 Successfully ingested {ingested_count} records into {memory_path}!")
    print(f"👉 Run 'npm run chat:unified -- --memory {memory_path}' to chat with this memory.")

if __name__ == "__main__":
    main()
