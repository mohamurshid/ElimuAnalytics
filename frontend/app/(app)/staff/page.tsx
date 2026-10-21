"use client";

/**
 * Teachers at the school: a head teacher's list.
 *
 * Adding a teacher makes an account with no password and shows a one-time
 * setup code, ONCE - only its hash is kept, so after this screen nobody,
 * the server included, can read it again. The head teacher passes it on;
 * the teacher sets their own password at "Set up your account". A teacher
 * who forgets their password gets a new code the same way, which also signs
 * them out everywhere.
 *
 * Deactivating takes effect at once on every device; reactivating restores
 * the account as it was. A school always keeps one active head teacher, and
 * the server says so if an action would leave it without one.
 *
 * Google sign-in, planned next, will use this same list as its gate.
 */

import { useCallback, useEffect, useState } from "react";

import { Badge, Button, Card, Field, Loading, Note, PageHeader } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { ROLE_LABEL } from "@/lib/people";
import type { StaffMember, StaffWithCode } from "@/lib/types";

type Role = "teacher" | "school_admin";

function when(iso: string | null): string {
  return iso ? new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "long" }) : "";
}

export default function StaffPage() {
  const { profile } = useAuth();
  const [staff, setStaff] = useState<StaffMember[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [code, setCode] = useState<StaffWithCode | null>(null);

  /** Re-read the list after an action. */
  const load = useCallback(async () => {
    try {
      setStaff(await api.get<StaffMember[]>("/api/staff"));
    } catch (e) {
      setError(errorMessage(e, "Could not load the teachers"));
    }
  }, []);

  // The first read: state is set only when the answer arrives, and not at
  // all if the page has gone - as the other pages load.
  useEffect(() => {
    let cancelled = false;
    api
      .get<StaffMember[]>("/api/staff")
      .then((list) => !cancelled && setStaff(list))
      .catch((e) => !cancelled && setError(errorMessage(e, "Could not load the teachers")));
    return () => {
      cancelled = true;
    };
  }, []);

  if (profile && profile.role === "teacher") {
    return (
      <>
        <PageHeader back={{ href: "/profile", label: "Profile" }} title="Teachers" />
        <Note>Only a head teacher can manage teachers&rsquo; accounts.</Note>
      </>
    );
  }

  function issued(result: StaffWithCode) {
    setCode(result);
    setAdding(false);
    void load();
  }

  return (
    <>
      <PageHeader
        back={{ href: "/profile", label: "Profile" }}
        title="Teachers"
        description={profile?.school}
        actions={
          !adding && (
            <Button onClick={() => { setAdding(true); setCode(null); }}>Add a teacher</Button>
          )
        }
      />

      <div className="space-y-4">
        <Note tone="error">{error}</Note>
        {code && <CodeCard result={code} onClose={() => setCode(null)} />}
        {adding && <AddForm onAdded={issued} onCancel={() => setAdding(false)} />}

        {!staff && !error && <Loading what="the teachers" />}
        {staff && (
          <Card>
            <ul className="divide-y divide-line">
              {staff.map((member) => (
                <StaffRow key={member.teacher_id} member={member} onChange={load} onCode={issued} />
              ))}
            </ul>
          </Card>
        )}
      </div>
    </>
  );
}

function CodeCard({ result, onClose }: { result: StaffWithCode; onClose: () => void }) {
  return (
    <Card className="border-ok/40 p-4">
      <h2 className="text-base font-semibold text-ink">Setup code for {result.name}</h2>
      <p
        className="mt-3 select-all rounded-md bg-sunken px-4 py-3 text-center font-mono text-3xl
                   font-semibold tracking-[0.2em] text-ink"
      >
        {result.setup_code}
      </p>
      <p className="mt-3 text-[15px] text-ink">
        Give this to {result.name}. They open the app, choose <strong>Set up your account</strong>,
        and enter <strong>{result.email}</strong>, this code and a password of their own.
      </p>
      <p className="mt-2 text-sm text-ink-muted">
        It works once and expires on {when(result.setup_code_expires_at)}.{" "}
        <strong>It won&rsquo;t be shown again</strong> - write it down now. If it is lost,
        give a new code.
      </p>
      <Button variant="secondary" size="sm" className="mt-3" onClick={onClose}>
        Done
      </Button>
    </Card>
  );
}

function AddForm({
  onAdded,
  onCancel,
}: {
  onAdded: (r: StaffWithCode) => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("teacher");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function add(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      onAdded(await api.post<StaffWithCode>("/api/staff", { name: name.trim(), email, role }));
    } catch (err) {
      setError(errorMessage(err, "Could not add the teacher"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="p-4">
      <form onSubmit={add} className="space-y-4">
        <h2 className="text-base font-semibold text-ink">Add a teacher</h2>
        <Field label="Name" required minLength={2} value={name}
               onChange={(e) => setName(e.target.value)} />
        <Field label="Email" type="email" inputMode="email" autoCapitalize="none"
               spellCheck={false} required value={email}
               onChange={(e) => setEmail(e.target.value)}
               hint="The address they will sign in with." />
        <RolePicker value={role} onChange={setRole} />
        <Note tone="error">{error}</Note>
        <div className="flex flex-wrap gap-2">
          <Button type="submit" disabled={busy}>{busy ? "Adding…" : "Add and show code"}</Button>
          <Button type="button" variant="secondary" disabled={busy} onClick={onCancel}>
            Cancel
          </Button>
        </div>
      </form>
    </Card>
  );
}

function RolePicker({ value, onChange }: { value: Role; onChange: (r: Role) => void }) {
  return (
    <label className="block">
      <span className="text-sm font-medium text-ink">Role</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value as Role)}
        className="mt-1.5 block min-h-11 w-full rounded-md border border-line-strong bg-surface
                   px-3 text-base text-ink"
      >
        <option value="teacher">Teacher</option>
        <option value="school_admin">Head teacher - can also manage teachers and classes</option>
      </select>
    </label>
  );
}

function StaffRow({
  member,
  onChange,
  onCode,
}: {
  member: StaffMember;
  onChange: () => Promise<void>;
  onCode: (r: StaffWithCode) => void;
}) {
  const [mode, setMode] = useState<"view" | "edit" | "confirm-code" | "confirm-off">("view");
  const [name, setName] = useState(member.name);
  const [email, setEmail] = useState(member.email);
  const [role, setRole] = useState<Role>(member.role === "school_admin" ? "school_admin" : "teacher");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const base = `/api/staff/${member.teacher_id}`;

  async function run<T>(work: () => Promise<T>, fallback: string) {
    setBusy(true);
    setError(null);
    try {
      const result = await work();
      setMode("view");
      return result;
    } catch (e) {
      setError(errorMessage(e, fallback));
      return null;
    } finally {
      setBusy(false);
    }
  }

  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (await run(() => api.patch(base, { name: name.trim(), email, role }), "Could not save")) {
      await onChange();
    }
  }

  async function newCode() {
    const result = await run(() => api.post<StaffWithCode>(`${base}/setup-code`), "Could not make a code");
    if (result) onCode(result);
  }

  async function toggle(action: "deactivate" | "reactivate") {
    if (await run(() => api.post(`${base}/${action}`), `Could not ${action} the account`)) {
      await onChange();
    }
  }

  return (
    <li className="px-4 py-3">
      <div className="flex flex-wrap items-start gap-x-3 gap-y-1">
        <div className="min-w-0 flex-1">
          <p className="text-[15px] font-medium text-ink">
            {member.name}
            {member.is_you && <span className="font-normal text-ink-muted"> (you)</span>}
          </p>
          <p className="break-all text-sm text-ink-muted">{member.email}</p>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {member.role !== "teacher" && <Badge>{ROLE_LABEL[member.role] ?? member.role}</Badge>}
            {member.status === "invited" && (
              <Badge tone="warn">
                Code not used yet{member.setup_code_expires_at
                  ? ` · expires ${when(member.setup_code_expires_at)}` : ""}
              </Badge>
            )}
            {member.status === "deactivated" && <Badge>Deactivated</Badge>}
          </div>
        </div>
        {mode === "view" && (
          <Button variant="ghost" size="sm" onClick={() => setMode("edit")}>
            Edit
          </Button>
        )}
      </div>

      <Note tone="error">{error}</Note>

      {mode === "view" && !member.is_you && (
        <div className="mt-2 flex flex-wrap gap-2">
          {member.is_active ? (
            <>
              <Button variant="secondary" size="sm" disabled={busy} onClick={() => setMode("confirm-code")}>
                New setup code
              </Button>
              <Button variant="secondary" size="sm" disabled={busy} onClick={() => setMode("confirm-off")}>
                Deactivate
              </Button>
            </>
          ) : (
            <Button variant="secondary" size="sm" disabled={busy} onClick={() => toggle("reactivate")}>
              Reactivate
            </Button>
          )}
        </div>
      )}

      {mode === "confirm-code" && (
        <div role="alertdialog" aria-label="New setup code" className="mt-3 rounded-md bg-warn-fill p-3">
          <p className="text-[15px] text-ink">
            Give {member.name} a new code? Their current password stops working and they are
            signed out everywhere until they use it.
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            <Button disabled={busy} onClick={newCode}>{busy ? "Making…" : "Make a new code"}</Button>
            <Button variant="secondary" disabled={busy} onClick={() => setMode("view")}>Cancel</Button>
          </div>
        </div>
      )}

      {mode === "confirm-off" && (
        <div role="alertdialog" aria-label="Deactivate" className="mt-3 rounded-md bg-risk-fill p-3">
          <p className="text-[15px] text-ink">
            Deactivate {member.name}? They are signed out everywhere at once and can&rsquo;t sign
            in. Their classes and records stay, and you can reactivate them later.
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            <Button variant="danger" disabled={busy} onClick={() => toggle("deactivate")}>
              {busy ? "Deactivating…" : "Deactivate"}
            </Button>
            <Button variant="secondary" disabled={busy} onClick={() => setMode("view")}>Cancel</Button>
          </div>
        </div>
      )}

      {mode === "edit" && (
        <form onSubmit={save} className="mt-3 space-y-4 rounded-md bg-sunken p-3">
          <Field label="Name" required minLength={2} value={name}
                 onChange={(e) => setName(e.target.value)} />
          <Field label="Email" type="email" required value={email} autoCapitalize="none"
                 onChange={(e) => setEmail(e.target.value)} />
          <RolePicker value={role} onChange={setRole} />
          <div className="flex flex-wrap gap-2">
            <Button type="submit" disabled={busy}>{busy ? "Saving…" : "Save"}</Button>
            <Button type="button" variant="secondary" disabled={busy} onClick={() => setMode("view")}>
              Cancel
            </Button>
          </div>
        </form>
      )}
    </li>
  );
}
