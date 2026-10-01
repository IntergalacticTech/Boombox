import { accountsApi } from "../accounts/api";
import type { Failure, RemoveResult, RetryResult, StorageOverview } from "./types";

/** Admin → Storage (/api/accounts/storage*, admin session). */
export const storageApi = {
  overview: () => accountsApi.get<StorageOverview | Failure>("storage"),
  remove: (kind: string, id: string) =>
    accountsApi.post<RemoveResult | Failure>("storage/remove", { kind, id }),
  retry: () => accountsApi.post<RetryResult | Failure>("storage/retry", {}),
};
