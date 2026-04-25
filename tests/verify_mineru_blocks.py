
import json
import os
import sys
from pathlib import Path

# Add docs-core to sys.path to allow importing RawFilesStructureBuilder
current_dir = Path(__file__).parent
project_root = current_dir.parent
docs_core_path = project_root / 'services' / 'docs-core' / 'src'
sys.path.insert(0, str(docs_core_path))

try:
    from docs_core.ingest.normalize.structure_builder import RawFilesStructureBuilder
except ImportError:
    print("Error: Could not import RawFilesStructureBuilder. Please ensure services/docs-core/src is in python path.")
    sys.exit(1)

def verify_mineru_blocks():
    # Paths
    base_dir = Path(r"d:\AI\AnGIneer\data\knowledge_base\libraries\default\documents\doc-ee0582c0\parsed\raw\cloud_result")
    
    # Files
    model_path = base_dir / "f2763a3a-e606-4dbc-ac03-f0c03836aa95_model.json"
    layout_path = base_dir / "layout.json"
    content_list_path = base_dir / "content_list_v2.json"
    
    print(f"--- Verifying MinerU Block Generation (A/B/C Fusion) ---")
    print(f"Base Dir: {base_dir}")
    
    # 1. Load Source Data
    print("\n[1] Loading Source Files...")
    
    if not model_path.exists():
        print(f"Error: model.json not found at {model_path}")
        return
    with open(model_path, 'r', encoding='utf-8') as f:
        model_data = json.load(f)
    print(f"  - Loaded Source A (Model): {len(model_data.get('model', [])) if isinstance(model_data, dict) else 'N/A'} pages")

    layout_data = None
    if layout_path.exists():
        with open(layout_path, 'r', encoding='utf-8') as f:
            layout_data = json.load(f)
        print(f"  - Loaded Source B (Layout): Yes")
    else:
        print(f"  - Warning: Source B (Layout) not found")

    content_list_data = None
    if content_list_path.exists():
        with open(content_list_path, 'r', encoding='utf-8') as f:
            content_list_data = json.load(f)
        print(f"  - Loaded Source C (Content List): Yes")
    else:
        print(f"  - Warning: Source C (Content List) not found")

    # 2. Generate Blocks using new Algorithm
    print("\n[2] Generating Blocks using RawFilesStructureBuilder...")
    builder = RawFilesStructureBuilder()
    generated_blocks = builder.build(model_data, layout_data, content_list_data)
    print(f"  - Generated {len(generated_blocks)} blocks")
    
    # 3. Validation
    print("\n[3] Validating against Sources...")
    
    # 3.1 Validate against Source A (Model)
    print("\n  [Check A] Model Content Integrity:")
    # Extract some text from model to check
    model_texts = []
    
    # Handle model_data as list or dict
    pages_data = []
    if isinstance(model_data, list):
        pages_data = model_data
    elif isinstance(model_data, dict) and 'model' in model_data:
        pages_data = model_data['model']
        
    for page in pages_data:
        if isinstance(page, list):
            # List of blocks
            for block in page:
                if isinstance(block, dict) and block.get('type') in ['text', 'header', 'footer', 'title']:
                    content = block.get('content')
                    if isinstance(content, str):
                        model_texts.append(content[:20])
        elif isinstance(page, dict):
            # Page object
            for block in page.get('blocks', []):
                if block.get('type') in ['text', 'header', 'footer', 'title']:
                    content = block.get('content')
                    if isinstance(content, str):
                        model_texts.append(content[:20])
    
    matched_count = 0
    sample_size = min(5, len(model_texts))
    for text_snippet in model_texts[:sample_size]:
        found = any(text_snippet in b.get('text', '') for b in generated_blocks)
        status = "OK" if found else "MISSING"
        print(f"    - Sample text '{text_snippet}...': {status}")
        if found: matched_count += 1
    
    print(f"    - Text Match Rate (Sample): {matched_count}/{sample_size}")

    # 3.2 Validate against Source B (Layout/Page Size)
    print("\n  [Check B] Page Dimensions (from Layout):")
    # Check first block's page size
    if generated_blocks:
        first_block = generated_blocks[0]
        w = first_block.get('page_width')
        h = first_block.get('page_height')
        print(f"    - Generated Block [0] Page Size: {w} x {h}")
        
        # Verify against layout.json
        layout_w = None
        layout_h = None
        if layout_data:
            if isinstance(layout_data, dict) and 'pdf_info' in layout_data:
                page_0 = layout_data['pdf_info'][0]
                layout_w = page_0.get('width') or page_0.get('w')
                layout_h = page_0.get('height') or page_0.get('h')
                
                # If layout.json missing direct w/h (as seen in previous analysis), check inference
                if layout_w is None:
                    print("    - Layout.json missing explicit width/height, checking inference logic...")
                    # Inference check logic is internal to builder, but we can see if we got values
        
        if w and h:
            print("    - PASS: Page dimensions are present.")
        else:
            print("    - FAIL: Page dimensions missing.")

    # 3.3 Validate against Source C (Content List / Hierarchy)
    print("\n  [Check C] Hierarchy & Levels (from Content List):")
    
    # Find blocks with levels
    leveled_blocks = [b for b in generated_blocks if b.get('level') is not None]
    print(f"    - Blocks with 'level' attribute: {len(leveled_blocks)}")
    
    if content_list_data:
        toc_items = content_list_data if isinstance(content_list_data, list) else content_list_data.get('content_list', [])
        print(f"    - Source C TOC Items: {len(toc_items)}")
        
        # Check if we have blocks matching these levels
        if leveled_blocks:
            print(f"    - Sample Leveled Block: {leveled_blocks[0].get('text')[:30]}... (Level {leveled_blocks[0].get('level')})")
        else:
             print("    - WARNING: No leveled blocks found. Check matching logic.")

    # 3.4 Validate Hierarchy (Parent/Child)
    print("\n  [Check D] Geometric Hierarchy (Parent/Child):")
    children_count = sum(1 for b in generated_blocks if b.get('parent_id'))
    parents_count = sum(1 for b in generated_blocks if b.get('children'))
    
    print(f"    - Blocks with parent_id: {children_count}")
    print(f"    - Blocks with children: {parents_count}")
    
    if children_count > 0:
        print("    - PASS: Hierarchy relationships detected.")
    else:
        print("    - WARNING: No hierarchy detected. Are blocks overlapping?")

    # 3.5 Validate 0/X/T/F/E Category Codes
    print("\n  [Check E] Category Codes (0/X/T/F/E):")
    codes = {}
    for b in generated_blocks:
        code = b.get('category_code', 'MISSING')
        codes[code] = codes.get(code, 0) + 1
    
    for code, count in codes.items():
        print(f"    - Code '{code}': {count} blocks")
        
    if 'MISSING' not in codes:
        print("    - PASS: All blocks have category codes.")
    else:
        print("    - FAIL: Some blocks missing category codes.")

    # 4. Save for inspection
    output_path = base_dir.parent / "mineru_blocks_debug.json"
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(generated_blocks, f, indent=2, ensure_ascii=False)
    print(f"\n[4] Saved generated blocks to {output_path}")

if __name__ == "__main__":
    verify_mineru_blocks()
