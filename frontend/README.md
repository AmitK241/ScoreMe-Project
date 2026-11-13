# Decision Platform - Frontend UI

Interactive Web Dashboard for the **Configurable Workflow Decision Platform**.

## Key Features

- **Dynamic Form Generation**: Reads the workflow's `input_schema` and automatically renders typed form inputs (text, numbers, booleans) or switches to a raw JSON editor.
- **Workflow & Sample Presets**: Easily switch between `application_approval`, `vendor_approval`, or custom workflows, and one-click populate realistic test scenarios.
- **Live Decision Inspector**: Visualizes the decision outcome (`APPROVED`, `REJECTED`, `MANUAL_REVIEW`, `RETRY_PENDING`, `INVALID`), reasons, and computed facts.
- **Rule Trace Visualizer**: Displays every evaluated rule in real-time, showing its stage, condition (`gte`, `lte`, `exists`, `not_in`), actual value vs expected value, and status (`passed`, `failed`, `skipped`).
- **Human Manual Review Action**: Enables risk officers to approve or reject pending `MANUAL_REVIEW` cases with reviewer name and notes directly from the UI.
- **Dependency Retry Action**: Retry external service dependencies on demand for `RETRY_PENDING` requests.
- **Audit Trail Timeline**: Step-by-step chronological visual audit trail of all lifecycle events and state transitions.
- **Request History & Metrics**: Real-time KPI cards and interactive historical requests table.
- **Workflow Architecture Viewer**: Live stage pipeline graph and configured rules catalog.

## Running the Frontend

The frontend has **zero external dependencies** and uses native Web standards.

### Option A: Using Node.js (Recommended)

From the project root:

```bash
# Using npm:
cd frontend
npm start

# Or directly with node:
node frontend/server.js
```

Then visit **http://localhost:3000** in your browser.

### Option B: Using Python HTTP Server

```bash
python -m http.server 3000 --directory frontend
```

Then visit **http://localhost:3000**.

