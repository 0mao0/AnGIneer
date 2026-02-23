# AnGIneer Backend Services

This directory contains the Python core services for AnGIneer subsystems.
Each service is designed to be a standalone Python package or microservice.

## Structure

- **`angineer-core`**: The OS Kernel (Dispatcher, Intent Classifier, Memory Manager).
- **`sop-core`**: SOP Engine (SOP Parser, Validator, Step Logic).
- **`docs-core`**: Knowledge Engine (RAG System, Document Ingestion).
- **`geo-core`**: Geo Engine (GIS Data Access, Spatial Calculations).
- **`engtools`**: Engineering Tools (Specialized Calculators, Utility Scripts).

## Integration

All services are integrated via the `Dispatcher` in `angineer-core`.
They communicate through the shared `Memory` (Blackboard Pattern).
