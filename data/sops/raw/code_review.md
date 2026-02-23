# 代码审查流程
Despcription:

## 实施步骤

### 1. Step 1

* **Tool**: `file_reader`

* **Inputs**:
  * `file_path`: ${file_path}

* **Outputs**:
  * `source_code`: .

### 2. Step 2

* **Tool**: `code_linter`

* **Inputs**:
  * `code`: ${source_code}

* **Outputs**:
  * `lint_issues`: .

### 3. Step 3

* **Tool**: `summarizer`

* **Inputs**:
  * `text`: Linting Issues Found:
${lint_issues}
  * `max_words`: 30

* **Outputs**:
  * `review_summary`: .

### 4. Step 4

* **Tool**: `report_generator`

* **Inputs**:
  * `title`: Code Review: ${file_path}
  * `data`: Source Length: ${source_code}

Issues:
${lint_issues}

Summary:
${review_summary}

* **Outputs**:
  * `final_report`: .