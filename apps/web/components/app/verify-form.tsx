"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { ArrowRight, CircleHelp, FilePlus2, Layers3, Scale, Zap } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import { useFirebaseAuth } from "@/components/providers/firebase-auth-provider";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Textarea } from "@/components/ui/form-controls";
import { apiErrorMessage, authenticatedApiFetch } from "@/lib/auth";
import { useActiveVerificationStore } from "@/stores/active-verification-store";

const verificationSchema = z.object({
  target: z.string().trim().min(1, "Enter a claim.").max(12000),
  researchDepth: z.enum(["QUICK", "STANDARD", "DEEP"]),
});

type VerificationFormValues = z.infer<typeof verificationSchema>;
type VerificationCreateResponse = { run_id: string; status: "QUEUED"; events_url: string };

const researchDepthOptions = [
  { value: "QUICK", label: "Quick", description: "Focused evidence breadth for simple claims, with expansion when discovery coverage is insufficient.", icon: Zap },
  { value: "STANDARD", label: "Standard", description: "Balanced evidence breadth with adaptive discovery. Recommended default.", icon: Scale },
  { value: "DEEP", label: "Deep", description: "The widest evidence breadth for complex or disputed submissions. Takes longer.", icon: Layers3 },
] as const;

export function VerifyForm() {
  const router = useRouter();
  const { user } = useFirebaseAuth();
  const resumeVerification = useActiveVerificationStore((state) => state.resume);
  const [apiError, setApiError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    control,
    formState: { errors, isSubmitting },
  } = useForm<VerificationFormValues>({
    resolver: zodResolver(verificationSchema),
    defaultValues: { researchDepth: "STANDARD", target: "" },
  });
  const target = useWatch({ control, name: "target" }) ?? "";
  const researchDepth = useWatch({ control, name: "researchDepth" });

  return (
    <div className="mx-auto max-w-4xl py-3 sm:py-8">
      <header className="mb-6 max-w-3xl">
        <h1 className="font-editorial text-[2.6rem] font-normal leading-[0.95] tracking-[-0.045em] text-foreground sm:text-[3.5rem]">Start a full verification</h1>
        <p className="mt-4 text-base leading-7 text-muted-foreground sm:text-lg">Submit the exact claim as written. Elara locates, reads, and evaluates timestamped evidence and returns transparent, citable results.</p>
      </header>
      <Card className="bg-card">
      <CardHeader className="border-b-0 px-6 pb-0 pt-6">
        <CardTitle className="font-serif text-2xl font-semibold">New verification</CardTitle>
      </CardHeader>
      <CardContent className="p-6 pt-4">
        <form
          className="grid gap-5"
          onSubmit={handleSubmit(async (values) => {
            if (!user) {
              setApiError("Sign in before starting a verification.");
              return;
            }
            setApiError(null);
            try {
              const payload = {
                input_type: "CLAIM",
                research_depth: values.researchDepth,
                text: values.target,
              };
              const response = await authenticatedApiFetch(user, "/v1/verifications", {
                method: "POST",
                body: JSON.stringify(payload),
              });
              if (!response.ok) {
                setApiError(await apiErrorMessage(response));
                return;
              }
              const created = (await response.json()) as VerificationCreateResponse;
              resumeVerification(created.run_id);
              router.push(`/verify/${created.run_id}`);
            } catch (error) {
              setApiError(error instanceof Error ? error.message : "Could not reach the verification API.");
            }
          })}
        >
          <fieldset aria-describedby="research-depth-help">
            <legend className="flex items-center gap-2 text-sm font-semibold">Research depth <CircleHelp className="h-4 w-4 text-muted-foreground" aria-label="Choose how broadly Elara should research this claim." /></legend>
            <p id="research-depth-help" className="mt-1 text-sm text-muted-foreground">Depth controls evidence breadth, not truth criteria or citation rigor. Discovery may expand when independent coverage is insufficient.</p>
            <div className="mt-3 grid gap-3 md:grid-cols-3">
              {researchDepthOptions.map(({ value, label, description, icon: Icon }) => (
                <label key={value} className="cursor-pointer">
                  <input type="radio" value={value} className="peer sr-only" {...register("researchDepth")} />
                  <span className={`flex min-h-36 flex-col rounded-md border bg-card p-4 text-left transition duration-200 peer-focus-visible:ring-2 peer-focus-visible:ring-ring peer-focus-visible:ring-offset-2 hover:border-primary/50 motion-reduce:transition-none ${researchDepth === value ? "border-primary bg-primary/5 ring-1 ring-primary" : ""}`}>
                    <span className="flex items-center gap-3 font-semibold"><Icon className="h-6 w-6 text-primary" aria-hidden="true" />{label}</span>
                    <span className="mt-3 text-sm leading-5 text-muted-foreground">{description}</span>
                  </span>
                </label>
              ))}
            </div>
          </fieldset>
          <div className="border-t pt-5">
          <label className="grid gap-2 text-sm font-semibold" htmlFor="verification-target">
            <span className="flex items-center justify-between gap-3">Claim <span className="text-xs font-normal text-muted-foreground">{target.length.toLocaleString()} / 12,000 characters</span></span>
            <Textarea
              {...register("target")}
              id="verification-target"
              maxLength={12000}
              placeholder="Paste the exact claim."
              aria-invalid={Boolean(errors.target)}
              aria-describedby={errors.target ? "verification-target-error" : undefined}
            />
          </label>
          {errors.target && <span id="verification-target-error" className="mt-2 block text-xs text-destructive" role="alert">{errors.target.message}</span>}
          <p className="mt-2 flex items-center gap-2 text-sm text-muted-foreground"><CircleHelp className="h-4 w-4 shrink-0 text-primary" aria-hidden="true" />Copy and paste the claim exactly as it appears in the source.</p>
          </div>
          <div className="flex flex-wrap items-center justify-between gap-3">
            {apiError && <p className="text-xs text-destructive" role="alert">{apiError}</p>}
            <Button type="submit" disabled={isSubmitting} className="ml-auto min-h-11 px-6">
              <FilePlus2 className="h-4 w-4" aria-hidden="true" />
              Create verification
              <ArrowRight className="h-4 w-4" aria-hidden="true" />
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
    </div>
  );
}
