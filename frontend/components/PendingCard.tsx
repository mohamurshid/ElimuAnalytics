"use client";

/**
 * Work kept on this device that has not reached the server yet - after a
 * dropped connection, a reload or a closed tab. Saving sends it with its
 * original batch id, so a save that had in fact landed is not recorded twice.
 * Discarding asks first: it is the only copy.
 */

import { useState } from "react";

import { Icon } from "@/components/Icon";
import { Button, Card, IconTile } from "@/components/ui";

export function PendingCard({
  description,
  busy,
  onSave,
  onDiscard,
}: {
  description: string;
  busy: boolean;
  onSave: () => void;
  onDiscard: () => void;
}) {
  const [asking, setAsking] = useState(false);
  return (
    <Card className="border-accent/50 p-4 sm:p-5">
      <div className="flex items-start gap-3">
        <IconTile name="save" tone="accent" />
        <div className="min-w-0 flex-1">
          <h2 className="text-base font-semibold text-ink">Not saved yet</h2>
          <p className="mt-0.5 text-[15px] text-ink-muted">
            {description} are kept on this device but haven’t reached the server.
          </p>
        </div>
      </div>
      {!asking ? (
        <div className="mt-4 flex flex-wrap gap-2">
          <Button disabled={busy} onClick={onSave}>
            <Icon name="save" className="size-4" />
            {busy ? "Saving…" : "Save them now"}
          </Button>
          <Button variant="secondary" disabled={busy} onClick={() => setAsking(true)}>
            Discard
          </Button>
        </div>
      ) : (
        <div role="alertdialog" aria-label="Discard unsaved answers" className="mt-4 rounded-xl bg-risk-fill p-4">
          <p className="text-[15px] text-ink">
            Discard them? This is the only copy, and it can’t be brought back.
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            <Button
              variant="danger"
              onClick={() => {
                setAsking(false);
                onDiscard();
              }}
            >
              Discard
            </Button>
            <Button variant="secondary" onClick={() => setAsking(false)}>
              Keep them
            </Button>
          </div>
        </div>
      )}
    </Card>
  );
}
