# GraphMind Frontend

React + TypeScript frontend for GraphMind.

## What Works Now

- Document upload panel
- Drag-and-drop upload
- Upload progress rows
- Stored document list
- Delete action for uploaded files
- Graph/search/chat panels with demo or fallback data

## Local Development

```bash
npm install
npm run dev
```

The app runs on `http://localhost:5173`.

Set the backend URL with:

```bash
VITE_API_URL=http://localhost:8000
```

## Useful Commands

```bash
npm run lint
npm run build
```

## Notes

- The upload view talks to the real backend document API.
- Graph, search, and chat are UI scaffolds for later backend modules.
- Shared state is kept intentionally small in `src/stores/appStore.ts`.
