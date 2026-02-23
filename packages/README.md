# AnGIneer Frontend Packages

This directory contains the Vue 3 component libraries for AnGIneer subsystems.
Each package is designed to be published independently to npm (private or public registry).

## Structure

- **`docs-ui`**: UI components for Docs Engine (PDF viewer, Knowledge graph, Search interface).
- **`sop-ui`**: UI components for SOP Engine (Flowchart visualization, Step execution monitor).
- **`geo-ui`**: UI components for Geo Engine (Map viewer, Layer control, GIS visualization).
- **`engtools-ui`**: UI components for Engineering Tools (Calculator, Unit Converters, Script runner).
- **`ui-kit`**: Shared base components (Buttons, Layouts, Theme, Common Widgets).

## Development

These packages are managed as a monorepo workspace.
Common dependencies are installed at the root level.
