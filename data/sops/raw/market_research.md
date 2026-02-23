# 市场调研流程
Despcription:

## 实施步骤

### 1. Step 1

* **Tool**: `web_search`

* **Inputs**:
  * `query`: ${topic} market trends 2025

* **Outputs**:
  * `market_data`: results

### 2. Step 2

* **Tool**: `web_search`

* **Inputs**:
  * `query`: top competitors in ${topic}

* **Outputs**:
  * `competitor_data`: results

### 3. Step 3

* **Tool**: `summarizer`

* **Inputs**:
  * `text`: Market Data: ${market_data}
Competitor Data: ${competitor_data}
  * `max_words`: 100

* **Outputs**:
  * `executive_summary`: .

### 4. Step 4

* **Tool**: `report_generator`

* **Inputs**:
  * `title`: ${topic} Market Research Report
  * `data`: ${executive_summary}

* **Outputs**:
  * `final_report`: .

### 5. Step 5

* **Tool**: `email_sender`

* **Inputs**:
  * `recipient`: boss@company.com
  * `subject`: Research: ${topic}
  * `body`: ${final_report}

* **Outputs**:
  * `email_status`: .