/* Upload page — the data-source switch (file vs database) and the DB table picker (Interim 2b).

   jsdom render tests over a mocked store + API client (no live server):
     • the source switch renders both tabs, with the file drop zone shown by default;
     • switching to "Import from database" fetches and lists the input DB's tables;
     • selecting a table profiles it (selectInputTable → applyUpload);
     • an empty table list and an unreachable DB show honest states. */

import { beforeEach, describe, expect, it, vi } from "vitest"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import type { ReactElement } from "react"

import type { InspectProfile } from "@/api/types"

// ── Store mock — the page needs inspect/serverPath/form + applyUpload/updateForm, plus the
//    §6.6 Step 6 Databricks fields (executionBackend/databricksPat/setDatabricksPat/running/
//    runPipeline) that gate the "Databricks (Unity Catalog)" data-source tab. ──
const applyUpload = vi.fn()
const updateForm = vi.fn()
const setDatabricksPat = vi.fn()
const runPipeline = vi.fn()
const mockApp = {
  inspect: null as InspectProfile | null,
  serverPath: null as string | null,
  form: { target: "", input_source: null, feature_cols: [] as string[] },
  applyUpload,
  updateForm,
  executionBackend: "local" as "local" | "databricks",
  databricksPat: "",
  setDatabricksPat,
  running: false,
  runPipeline,
}
vi.mock("@/store/AppStore", () => ({ useApp: () => mockApp }))

// ── API client mock (shared by Upload + DatabaseSourcePanel + DatabricksSourcePanel). ──
const listInputTables = vi.fn()
const selectInputTable = vi.fn()
const uploadFile = vi.fn()
const listCatalogs = vi.fn()
const listSchemas = vi.fn()
const listTables = vi.fn()
vi.mock("@/api/client", () => ({
  listInputTables: () => listInputTables(),
  selectInputTable: (args: unknown) => selectInputTable(args),
  upload: (...args: unknown[]) => uploadFile(...args),
  listCatalogs: (pat: string) => listCatalogs(pat),
  listSchemas: (catalog: string, pat: string) => listSchemas(catalog, pat),
  listTables: (catalog: string, schema: string, pat: string) => listTables(catalog, schema, pat),
  ApiError: class ApiError extends Error {},
}))

import { ApiError } from "@/api/client"
import UploadPage from "./Upload"

const DB_PROFILE: InspectProfile = {
  columns: ["sepal_length", "species"],
  dtypes: { sepal_length: "float64", species: "object" },
  numeric_cols: ["sepal_length"],
  categorical_cols: ["species"],
  binary_cols: [],
  datetime_cols: [],
  n_rows: 150,
  n_missing: { sepal_length: 0, species: 0 },
  sample: [],
  server_path: "db_snapshots/iris.parquet",
  input_source: { type: "postgres", connection_env: "CLASSIFYOS_PG_DSN", table: "iris", query: null },
}

beforeEach(() => {
  listInputTables.mockReset()
  selectInputTable.mockReset()
  uploadFile.mockReset()
  applyUpload.mockReset()
  updateForm.mockReset()
  setDatabricksPat.mockReset()
  runPipeline.mockReset()
  mockApp.inspect = null
  mockApp.serverPath = null
  mockApp.form = { target: "", input_source: null, feature_cols: [] }
  mockApp.executionBackend = "local"
  mockApp.databricksPat = ""
  mockApp.running = false
})

function renderPage(ui: ReactElement) {
  return render(<MemoryRouter>{ui}</MemoryRouter>)
}

describe("Upload — source switch", () => {
  it("shows both source tabs and the file drop zone by default", () => {
    renderPage(<UploadPage />)
    expect(screen.getByRole("tab", { name: /Upload a file/i })).toBeInTheDocument()
    expect(screen.getByRole("tab", { name: /Import from database/i })).toBeInTheDocument()
    expect(screen.getByText(/Drag a file here/i)).toBeInTheDocument()
    // The DB panel is not mounted until its tab is chosen → no fetch yet.
    expect(listInputTables).not.toHaveBeenCalled()
  })

  it("lists the input DB tables after switching to the database source", async () => {
    listInputTables.mockResolvedValue({
      connection_env: "CLASSIFYOS_PG_DSN",
      tables: ["arizona", "iris"],
    })
    renderPage(<UploadPage />)
    fireEvent.click(screen.getByRole("tab", { name: /Import from database/i }))

    expect(await screen.findByText("iris")).toBeInTheDocument()
    expect(screen.getByText("arizona")).toBeInTheDocument()
  })

  it("profiles a table when picked (selectInputTable → applyUpload)", async () => {
    listInputTables.mockResolvedValue({
      connection_env: "CLASSIFYOS_PG_DSN",
      tables: ["iris"],
    })
    selectInputTable.mockResolvedValue(DB_PROFILE)
    renderPage(<UploadPage />)
    fireEvent.click(screen.getByRole("tab", { name: /Import from database/i }))

    fireEvent.click(await screen.findByText("iris"))
    await waitFor(() =>
      expect(selectInputTable).toHaveBeenCalledWith(expect.objectContaining({ table: "iris" })),
    )
    expect(applyUpload).toHaveBeenCalledWith(DB_PROFILE)
  })
})

describe("Upload — database honest states", () => {
  it("shows an empty state when the DB has no tables", async () => {
    listInputTables.mockResolvedValue({ connection_env: "CLASSIFYOS_PG_DSN", tables: [] })
    renderPage(<UploadPage />)
    fireEvent.click(screen.getByRole("tab", { name: /Import from database/i }))
    expect(await screen.findByText(/No tables found/i)).toBeInTheDocument()
  })

  it("shows an error state when the database is unreachable", async () => {
    listInputTables.mockRejectedValue(new ApiError("input database unavailable: Postgres is down"))
    renderPage(<UploadPage />)
    fireEvent.click(screen.getByRole("tab", { name: /Import from database/i }))
    expect(await screen.findByText(/Database unreachable/i)).toBeInTheDocument()
    expect(screen.getByText(/Postgres is down/i)).toBeInTheDocument()
  })
})

describe("Upload — Databricks data source (§6.6 Step 6, toggle show/hide)", () => {
  it("hides the Databricks tab in the LOCAL execution backend", () => {
    mockApp.executionBackend = "local"
    renderPage(<UploadPage />)
    expect(screen.queryByRole("tab", { name: /Databricks/i })).not.toBeInTheDocument()
  })

  it("shows the Databricks tab (with the PAT input + catalog browser) in the DATABRICKS backend", async () => {
    mockApp.executionBackend = "databricks"
    listCatalogs.mockResolvedValue({ catalogs: ["main", "samples"] })
    renderPage(<UploadPage />)

    const tab = screen.getByRole("tab", { name: /Databricks/i })
    expect(tab).toBeInTheDocument()
    fireEvent.click(tab)

    // The PAT input appears; browsing needs it, so Connect drives listCatalogs.
    const pat = screen.getByLabelText(/personal access token/i)
    fireEvent.change(pat, { target: { value: "dapi-xyz" } })
    expect(setDatabricksPat).toHaveBeenCalledWith("dapi-xyz")
  })

  it("lists catalogs after Connect and passes the PAT through", async () => {
    mockApp.executionBackend = "databricks"
    mockApp.databricksPat = "dapi-xyz"
    listCatalogs.mockResolvedValue({ catalogs: ["main", "samples"] })
    renderPage(<UploadPage />)
    fireEvent.click(screen.getByRole("tab", { name: /Databricks/i }))
    fireEvent.click(screen.getByRole("button", { name: /Connect/i }))

    await waitFor(() => expect(listCatalogs).toHaveBeenCalledWith("dapi-xyz"))
    // The catalog dropdown is populated.
    expect(await screen.findByRole("option", { name: "main" })).toBeInTheDocument()
  })
})
