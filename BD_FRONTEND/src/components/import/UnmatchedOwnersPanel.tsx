"use client";

/**
 * Owner assignment panel for a completed import (task M2-A4 UI; D-075).
 *
 * Needed so a manager can give the leads whose source owner text matched no user to an app
 * user, one owner text at a time. The server lists the groups, only fills empty owners and
 * audits the change; this component shows its answers (including how many leads already had an
 * owner and were left alone) and holds no rules. Owner texts come from the uploaded file, so they
 * are rendered as plain text only.
 */
import { useCallback, useEffect, useState } from "react";

import "@/lib/api-client";
import {
  getAssignableUsersImportsAssignableUsersGet,
  getUnmatchedOwnersImportsImportIdUnmatchedOwnersGet,
  postAssignOwnerImportsImportIdAssignOwnerPost,
} from "@/lib/api/sdk.gen";
import type { AssignableUserResponse, UnmatchedOwnerResponse } from "@/lib/api/types.gen";
import { errorMessage } from "@/lib/import/errors";

type Props = Readonly<{ importId: string }>;

const BLANK_GROUP_LABEL = "(no owner given)";
const MESSAGE_ALL_OWNED = "Every lead from this import has an owner.";

/** Renders the unmatched owner texts, each with a user picker and an Assign button. */
export default function UnmatchedOwnersPanel({ importId }: Props) {
  const [groups, setGroups] = useState<UnmatchedOwnerResponse[] | null>(null);
  const [users, setUsers] = useState<AssignableUserResponse[]>([]);
  // Chosen user per owner_group (the empty string is the "no owner given" group).
  const [chosen, setChosen] = useState<Record<string, string>>({});
  const [busyGroup, setBusyGroup] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadGroups = useCallback(async () => {
    const result = await getUnmatchedOwnersImportsImportIdUnmatchedOwnersGet({
      path: { import_id: importId },
    });
    if (result.data) setGroups(result.data);
    else setError(errorMessage(result.error, result.response));
  }, [importId]);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      const people = await getAssignableUsersImportsAssignableUsersGet();
      if (cancelled) return;
      if (people.data) setUsers(people.data);
      else setError(errorMessage(people.error, people.response));
      await loadGroups();
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [loadGroups]);

  /** Assigns one group to the chosen user, reports the counts and reloads the list. */
  async function assign(group: UnmatchedOwnerResponse) {
    const userId = chosen[group.owner_group];
    if (!userId) return;
    setError(null);
    setNotice(null);
    setBusyGroup(group.owner_group);
    const result = await postAssignOwnerImportsImportIdAssignOwnerPost({
      path: { import_id: importId },
      body: { owner_group: group.owner_group, user_id: userId },
    });
    setBusyGroup(null);
    if (result.data) {
      const { assigned, skipped } = result.data;
      setNotice(
        `Assigned ${assigned} lead${assigned === 1 ? "" : "s"}` +
          (skipped > 0 ? `; ${skipped} already had an owner and were left as they are.` : "."),
      );
      await loadGroups();
      return;
    }
    setError(errorMessage(result.error, result.response));
  }

  if (groups === null) {
    return error ? <p role="alert">{error}</p> : <p>Loading owners…</p>;
  }

  return (
    <section aria-labelledby="owners-title">
      <h3 id="owners-title">Leads without an owner</h3>
      {error && <p role="alert">{error}</p>}
      {notice && <p role="status">{notice}</p>}
      {groups.length === 0 ? (
        <p>{MESSAGE_ALL_OWNED}</p>
      ) : (
        <>
          <p>
            The owner named in the file matched no user. Choose who should own each group of leads.
          </p>
          <table>
            <thead>
              <tr>
                <th scope="col">Owner in the file</th>
                <th scope="col">Leads</th>
                <th scope="col">Assign to</th>
                <th scope="col">Action</th>
              </tr>
            </thead>
            <tbody>
              {groups.map((group) => {
                const label = group.is_blank ? BLANK_GROUP_LABEL : group.display_name;
                return (
                  <tr key={group.owner_group}>
                    <th scope="row">{label}</th>
                    <td>{group.lead_count}</td>
                    <td>
                      <select
                        aria-label={`Assign ${label} to`}
                        value={chosen[group.owner_group] ?? ""}
                        onChange={(event) =>
                          setChosen({ ...chosen, [group.owner_group]: event.target.value })
                        }
                      >
                        <option value="">Choose a user…</option>
                        {users.map((user) => (
                          <option key={user.id} value={user.id}>
                            {user.email}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td>
                      <button
                        className="button"
                        type="button"
                        disabled={!chosen[group.owner_group] || busyGroup !== null}
                        onClick={() => void assign(group)}
                      >
                        {busyGroup === group.owner_group ? "Assigning…" : "Assign"}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </>
      )}
    </section>
  );
}
