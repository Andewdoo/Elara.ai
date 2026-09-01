"use client";

import { Clock3 } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef } from "react";

import { Button } from "@/components/ui/button";

type VerifierUnavailableDialogProps = {
  open: boolean;
  onClose: () => void;
};

export function VerifierUnavailableDialog({ open, onClose }: VerifierUnavailableDialogProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;

    if (open && !dialog.open) {
      dialog.showModal();
    } else if (!open && dialog.open) {
      dialog.close();
    }
  }, [open]);

  return (
    <dialog
      ref={dialogRef}
      aria-labelledby="verifier-unavailable-title"
      aria-describedby="verifier-unavailable-description"
      className="m-auto w-[calc(100%-2rem)] max-w-lg overflow-hidden rounded-lg border-0 bg-card p-0 text-card-foreground shadow-2xl backdrop:bg-slate-950/55"
      onCancel={onClose}
      onClose={onClose}
    >
      <div className="flex items-start gap-4 px-5 pb-4 pt-5 sm:px-6 sm:pt-6">
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-secondary text-primary">
          <Clock3 className="h-5 w-5" aria-hidden="true" />
        </span>
        <div className="min-w-0">
          <h2 id="verifier-unavailable-title" className="font-serif text-xl font-semibold leading-7">
            Full Verifier is currently unavailable
          </h2>
          <p id="verifier-unavailable-description" className="mt-2 text-sm leading-6 text-muted-foreground">
            Full Verifier is unavailable right now and may be available during the daily 9:00 AM–9:00 PM ET window. We’re sorry for the inconvenience; you can view the Demo archive for examples in the meantime.
          </p>
        </div>
      </div>
      <div className="flex flex-col-reverse gap-2 border-t bg-muted/35 px-5 py-4 sm:flex-row sm:justify-end sm:px-6">
        <Button variant="secondary" className="w-full sm:w-auto" onClick={() => dialogRef.current?.close()}>
          Close
        </Button>
        <Button asChild className="w-full sm:w-auto">
          <Link href="/" onClick={onClose}>View Demo archive</Link>
        </Button>
      </div>
    </dialog>
  );
}
