"""Risky code-file open test.

Expected behavior:
- Upload succeeds.
- Clicking the open-file button downloads this file instead of previewing it inline.
- Response header should use Content-Disposition: attachment.
"""

print("This Python file should download, not execute in the browser.")
