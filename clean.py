import json
import pandas as pd
from typing import Dict, Any, Tuple

def load_export(file_bytes: bytes, filename: str) -> Tuple[str, pd.DataFrame, pd.DataFrame, Dict[str, Any]]:
    """
    Step 1: Workbook Import
    Pass Condition: Handles both XLSX and CSV uniformly. Normalizes spaces/cases.
    """
    # 1. Determine file type and read into dataframe
    if filename.endswith('.xlsx'):
        df = pd.read_excel(file_bytes, sheet_name="Survey Data")
    else:
        df = pd.read_csv(file_bytes, encoding='utf-8')
        
    # 2. Normalize columns (lowercase, strip trailing spaces, remove non-breaking spaces)
    df.columns = df.columns.str.lower().str.replace(r'\s+', ' ', regex=True).str.strip()
    
    # 3. Validation check for required fields
    required_fields = ['id', 'q1_knowledge', 'q2_knowledge', 'q3_knowledge', 'q4_knowledge', 'q5_knowledge', 'q6_knowledge']
    missing = [f for f in required_fields if f not in df.columns]
    if missing:
        raise ValueError(f"Missing required fields: {', '.join(missing)}")
        
    dataset_key = f"DS_{hash(filename) % 10000}"
    
    # Extract structural responses and mask private comments
    normalized_responses = df[required_fields].copy()
    private_comments = df[['id', 'open_text_feedback']].copy() if 'open_text_feedback' in df.columns else pd.DataFrame()
    
    audit_summary = {
        "total_rows": len(df),
        "columns_mapped": list(df.columns),
        "has_optional_intent": 'intent' in df.columns
    }
    
    return dataset_key, normalized_responses, private_comments, audit_summary