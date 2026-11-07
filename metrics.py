import pandas as pd
from typing import List, Dict, Any

def build_evidence(dataset_df: pd.DataFrame, audience: str) -> List[Dict[str, Any]]:
    """
    Step 2: Audience and Evidence with strict Privacy Suppression
    Pass Condition: Groups under 10 reveal 0 stats or paraphrases down the chain.
    """
    # 1. Filter by target audience
    audience_df = dataset_df[dataset_df['role'] == audience] if 'role' in dataset_df.columns else dataset_df
    sample_size = len(audience_df)
    
    evidence_rows = []
    
    # 2. Check strict Privacy Threshold
    if sample_size < 10:
        # Enforce complete suppression block
        return []
        
    # 3. Calculate agreement metrics (Example for 988 Post)
    # Target values: 4 (Agree) and 5 (Strongly Agree)
    valid_rows = audience_df['q1_knowledge'].dropna()
    numerator = int(valid_rows.isin([4, 5]).sum())
    denominator = int(len(valid_rows))
    
    pct = (numerator / denominator * 100) if denominator > 0 else 0.0
    
    evidence_rows.append({
        "dataset_key": "E01",
        "audience": audience,
        "evidence_id": "EV_988_POST_01",
        "survey_question": "post-training agreement on explaining 988",
        "metric_type": "retrospective_agreement",
        "numerator_or_score_sum": numerator,
        "valid_denominator": denominator,
        "audience_total": sample_size,
        "unit": "percent",
        "display_value": f"{pct:.1f}%",
        "caveat": "Limited sample size" if sample_size < 30 else "none"
    })
    
    return evidence_rows