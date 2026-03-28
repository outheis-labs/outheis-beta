# Code Agent Skills (alan)

## Code Reading

- Read the actual file before making any claim about implementation
- Cite file path and line number when referencing code
- For call chains, trace them step by step with read_file

## Proposals

- Every proposed change goes through vault/Codebase/Exchange.md
- Write staged files to vault/Codebase/<filename> for non-trivial changes
- Exchange.md entry format:
  ```
  ## YYYY-MM-DD — Short title
  **Type:** refactor | bugfix | improvement | answer
  **Files:** path/to/file.py
  **Status:** proposed
  ### Summary
  What and why.
  ### Proposed Change
  Reference to staged file or inline diff.
  ### Discussion
  ```
- Never modify src/ directly — write_codebase enforces this

## Search Strategy

- Use search_code for function names, class names, patterns
- Use list_files to orient in unfamiliar directories
- Prefer reading specific files over broad search when the index shows the relevant file
