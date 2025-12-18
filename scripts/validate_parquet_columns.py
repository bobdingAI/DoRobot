import sys
import pandas as pd
from pathlib import Path

def verify_parquet(parquet_path: str):
    path = Path(parquet_path)
    if not path.exists():
        print(f"Error: File not found at {parquet_path}")
        return False
    
    try:
        df = pd.read_parquet(path)
        print(f"Successfully loaded parquet: {parquet_path}")
        print(f"Columns found: {list(df.columns)}")
        
        image_columns = [col for col in df.columns if "observation.images" in col]
        if not image_columns:
            print("❌ FAILURE: No image columns found in parquet file!")
            return False
        else:
            print(f"✅ SUCCESS: Found {len(image_columns)} image columns: {image_columns}")
            # Check for data presence
            first_val = df[image_columns[0]].iloc[0]
            print(f"Sample data from {image_columns[0]}: {first_val}")
            return True
            
    except Exception as e:
        print(f"Error reading parquet: {e}")
        return False

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/validate_parquet_columns.py <path_to_parquet>")
        sys.exit(1)
    
    success = verify_parquet(sys.argv[1])
    sys.exit(0 if success else 1)

