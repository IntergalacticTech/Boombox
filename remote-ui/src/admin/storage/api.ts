import { accountsApi } from "../accounts/api";
import type { Failure, RemoveResult, RetryResult, StorageOverview } from "./types";
import type { BrowseResult, FilesClient } from "../../screens/Files";

/** Admin → Storage (/api/accounts/storage*, admin session). */
export const storageApi = {
  overview: () => accountsApi.get<StorageOverview | Failure>("storage"),
  remove: (kind: string, id: string) =>
    accountsApi.post<RemoveResult | Failure>("storage/remove", { kind, id }),
  retry: () => accountsApi.post<RetryResult | Failure>("storage/retry", {}),
};

/** Admin → Storage file browser: browse / upload / delete with the admin
 *  session. accountsApi resolves JSON error bodies, so turn them into throws. */
export const adminFilesClient: FilesClient = {
  async browse(path) {
    const r = await accountsApi.get<BrowseResult | { error?: string }>(
      `storage/files/browse?path=${encodeURIComponent(path)}`);
    if ("entries" in r) return r;
    throw new Error(r.error || "Couldn't list the files");
  },
  async upload(files) {
    const r = await accountsApi.upload<{ saved?: string[]; error?: string }>("storage/files/upload", files);
    if (Array.isArray(r.saved)) return { saved: r.saved };
    throw new Error(r.error || "Upload failed");
  },
  async remove(path) {
    const r = await accountsApi.post<{ deleted?: string; error?: string }>("storage/files/delete", { path });
    if (r.deleted === undefined) throw new Error(r.error || "Delete failed");
    return r;
  },
};
