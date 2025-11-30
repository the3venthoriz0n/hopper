#!/usr/bin/env python3
"""
Migration script to help refactor main.py from file-based sessions to database
This script performs systematic replacements to migrate endpoints
"""

import re
import sys
from pathlib import Path

def migrate_main_py(file_path: Path):
    """Migrate main.py to use database instead of file-based sessions"""
    
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    original_content = content
    
    print("🔄 Starting migration...")
    
    # 1. Update imports (already done in previous steps)
    
    # 2. Replace dependency injections
    replacements = [
        # Replace session dependencies with auth dependencies
        (r'session_id:\s*str\s*=\s*Depends\(get_or_create_session\)', 
         'user_id: int = Depends(require_auth)'),
        
        (r'session_id:\s*str\s*=\s*Depends\(require_session\)', 
         'user_id: int = Depends(require_auth)'),
        
        (r'session_id:\s*str\s*=\s*Depends\(require_csrf\)', 
         'user_id: int = Depends(require_csrf_new)'),
        
        # Replace session access patterns
        (r'session\s*=\s*get_session\(session_id\)\s*\n', 
         ''),
        
        (r'save_session\(session_id\)', 
         '# Session now auto-saved to database'),
    ]
    
    for pattern, replacement in replacements:
        old_content = content
        content = re.sub(pattern, replacement, content)
        if content != old_content:
            print(f"✅ Replaced pattern: {pattern[:50]}...")
    
    # 3. Comment out old session-related functions (don't delete yet, for reference)
    functions_to_comment = [
        'def get_session(',
        'def save_session(',
        'def load_session(',
        'def get_or_create_session_id(',
    ]
    
    for func_name in functions_to_comment:
        if func_name in content:
            # Find the function and comment it out
            pattern = f'({func_name}[^\\n]*)'
            content = re.sub(pattern, r'# DEPRECATED: \1', content)
            print(f"✅ Commented out: {func_name}")
    
    # 4. Save if changes were made
    if content != original_content:
        # Create backup
        backup_path = file_path.with_suffix('.py.backup')
        with open(backup_path, 'w', encoding='utf-8') as f:
            f.write(original_content)
        print(f"💾 Backup saved to: {backup_path}")
        
        # Write new content
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"✅ Migration complete! Updated {file_path}")
        print("\n⚠️  IMPORTANT: Review the changes and manually update endpoint logic to use db_helpers")
    else:
        print("ℹ️  No changes needed")
    
    return content != original_content

if __name__ == "__main__":
    main_py = Path(__file__).parent / "backend" / "main.py"
    
    if not main_py.exists():
        print(f"❌ Error: {main_py} not found")
        sys.exit(1)
    
    print(f"📂 Migrating: {main_py}")
    print("=" * 60)
    
    changed = migrate_main_py(main_py)
    
    if changed:
        print("\n" + "=" * 60)
        print("✨ Migration script completed!")
        print("\n📋 Next steps:")
        print("1. Review the changes in main.py")
        print("2. Update endpoint logic to use db_helpers functions")
        print("3. Test all endpoints")
        print("4. Remove old commented code once verified")
    else:
        print("\nNo automatic migrations needed.")

