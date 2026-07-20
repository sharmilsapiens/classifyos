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
  form: { target: "", input_source: null, feature_cols: [] as string[], cluster_id: "" },
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
const listClusters = vi.fn()
const getTableProfile = vi.fn()
vi.mock("@/api/client", () => ({
  listInputTables: () => listInputTables(),
  selectInputTable: (args: unknown) => selectInputTable(args),
  upload: (...args: unknown[]) => uploadFile(...args),
  listCatalogs: (pat: string) => listCatalogs(pat),
  listSchemas: (catalog: string, pat: string) => listSchemas(catalog, pat),
  listTables: (catalog: string, schema: string, pat: string) => listTables(catalog, schema, pat),
  listClusters: (pat: string) => listClusters(pat),
  getTableProfile: (args: unknown, pat: string) => getTableProfile(args, pat),
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

// Schema-only profile a UC table-profile fetch returns: the InspectProfile shape (columns, dtypes,
// column groups) + a `delta` input_source + a snapshot server_path. Row-level stats are zeroed
// (unavailable from schema-only metadata).
const UC_PROFILE: InspectProfile = {
  columns: ["age", "region", "has_agent"],
  dtypes: { age: "int", region: "string", has_agent: "boolean" },
  numeric_cols: ["age"],
  categorical_cols: ["region", "has_agent"],
  binary_cols: ["has_agent"],
  datetime_cols: [],
  n_rows: 0,
  n_missing: { age: 0, region: 0, has_agent: 0 },
  sample: [],
  server_path: "db_snapshots/main_insurance_policy_lapse.parquet",
  input_source: {
    type: "delta",
    connection_env: "CLASSIFYOS_PG_DSN",
    catalog: "main",
    schema: "insurance",
    table: "policy_lapse",
    query: null,
  },
}

/** Drive the UC cascade to a ready table list: connect → pick catalog → pick schema. */
async function browseToTables() {
  listCatalogs.mockResolvedValue({ catalogs: ["main"] })
  listSchemas.mockResolvedValue({ schemas: ["insurance"] })
  listTables.mockResolvedValue({ tables: ["policy_lapse"] })
  fireEvent.click(screen.getByRole("tab", { name: /Databricks/i }))
  fireEvent.click(screen.getByRole("button", { name: /Connect/i }))
  await screen.findByRole("option", { name: "main" })
  fireEvent.change(screen.getByLabelText(/^Catalog$/i), { target: { value: "main" } })
  await waitFor(() => expect(listSchemas).toHaveBeenCalledWith("main", "dapi-xyz"))
  fireEvent.change(await screen.findByLabelText(/^Schema$/i), { target: { value: "insurance" } })
  await waitFor(() => expect(listTables).toHaveBeenCalledWith("main", "insurance", "dapi-xyz"))
}

beforeEach(() => {
  listInputTables.mockReset()
  selectInputTable.mockReset()
  uploadFile.mockReset()
  listCatalogs.mockReset()
  listSchemas.mockReset()
  listTables.mockReset()
  listClusters.mockReset()
  // Connect always fetches the cluster list; default to none so the UC-browse tests are unaffected.
  listClusters.mockResolvedValue({ clusters: [] })
  getTableProfile.mockReset()
  applyUpload.mockReset()
  updateForm.mockReset()
  setDatabricksPat.mockReset()
  runPipeline.mockReset()
  mockApp.inspect = null
  mockApp.serverPath = null
  mockApp.form = { target: "", input_source: null, feature_cols: [], cluster_id: "" }
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

  it("Connect fetches clusters; picking one sets cluster_id on the run config", async () => {
    mockApp.executionBackend = "databricks"
    mockApp.databricksPat = "dapi-xyz"
    listCatalogs.mockResolvedValue({ catalogs: ["main"] })
    listClusters.mockResolvedValue({
      clusters: [
        { cluster_id: "0716-run", cluster_name: "prod-cluster", state: "RUNNING" },
        { cluster_id: "0716-term", cluster_name: "dev-cluster", state: "TERMINATED" },
      ],
    })
    renderPage(<UploadPage />)
    fireEvent.click(screen.getByRole("tab", { name: /Databricks/i }))
    fireEvent.click(screen.getByRole("button", { name: /Connect/i }))

    await waitFor(() => expect(listClusters).toHaveBeenCalledWith("dapi-xyz"))
    // Picking a cluster pushes its id into the run config (→ overrides the env var default).
    const clusterSelect = await screen.findByLabelText(/^Cluster$/i)
    fireEvent.change(clusterSelect, { target: { value: "0716-run" } })
    expect(updateForm).toHaveBeenCalledWith({ cluster_id: "0716-run" })

    // Clearing the choice ("server default") sends "" → the server falls back to the env var.
    fireEvent.change(clusterSelect, { target: { value: "" } })
    expect(updateForm).toHaveBeenCalledWith({ cluster_id: "" })
  })
})

describe("Upload — Databricks table profiling (schema fetch → shared column picker)", () => {
  it("shows a loading state then profiles a UC table (getTableProfile → applyUpload)", async () => {
    mockApp.executionBackend = "databricks"
    mockApp.databricksPat = "dapi-xyz"
    // A deferred promise so the "Loading table schema…" state is observable before it resolves.
    let resolveProfile: (p: InspectProfile) => void = () => {}
    getTableProfile.mockReturnValue(
      new Promise<InspectProfile>((res) => {
        resolveProfile = res
      }),
    )
    renderPage(<UploadPage />)
    await browseToTables()

    fireEvent.click(await screen.findByText(/main\.insurance\.policy_lapse/i))

    // The PAT + the exact selection are forwarded to the profile endpoint.
    await waitFor(() =>
      expect(getTableProfile).toHaveBeenCalledWith(
        { catalog: "main", schema: "insurance", table: "policy_lapse" },
        "dapi-xyz",
      ),
    )
    // Loading state appears while the schema is fetched.
    expect(await screen.findByText(/Loading table schema/i)).toBeInTheDocument()

    // On success the profile flows through the SAME applyUpload plumbing as an uploaded file.
    resolveProfile(UC_PROFILE)
    await waitFor(() => expect(applyUpload).toHaveBeenCalledWith(UC_PROFILE))
  })

  it("shows an error when the table schema can't be fetched", async () => {
    mockApp.executionBackend = "databricks"
    mockApp.databricksPat = "dapi-xyz"
    getTableProfile.mockRejectedValue(new ApiError("Databricks unavailable: workspace down"))
    renderPage(<UploadPage />)
    await browseToTables()

    fireEvent.click(await screen.findByText(/main\.insurance\.policy_lapse/i))
    expect(await screen.findByText(/workspace down/i)).toBeInTheDocument()
    expect(applyUpload).not.toHaveBeenCalled()
  })

  it("populates the shared column picker (columns, types, target dropdown) from the UC profile", () => {
    // When a UC profile is in the store, the same inspection UI a CSV upload shows renders — the
    // column table (with types + a binary badge) and the target dropdown, no manual entry.
    mockApp.executionBackend = "databricks"
    mockApp.databricksPat = "dapi-xyz"
    mockApp.inspect = UC_PROFILE
    mockApp.serverPath = UC_PROFILE.server_path
    renderPage(<UploadPage />)

    // The UC data types are shown in the columns table (unique to the dtype cells).
    expect(screen.getByText("int")).toBeInTheDocument()
    expect(screen.getByText("string")).toBeInTheDocument()
    expect(screen.getByText("boolean")).toBeInTheDocument()
    // The boolean column carries the "binary" badge (schema-derived).
    expect(screen.getByText("binary")).toBeInTheDocument()
    // The target dropdown offers every column — the user picks, never types.
    expect(screen.getByRole("option", { name: "age" })).toBeInTheDocument()
    expect(screen.getByRole("option", { name: "region" })).toBeInTheDocument()
    expect(screen.getByRole("option", { name: "has_agent" })).toBeInTheDocument()
  })
})
