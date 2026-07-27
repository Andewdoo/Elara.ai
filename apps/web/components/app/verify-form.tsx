"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { ArrowRight } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import { useFirebaseAuth } from "@/components/providers/firebase-auth-provider";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Select, Textarea } from "@/components/ui/form-controls";
import { apiErrorMessage, authenticatedApiFetch } from "@/lib/auth";
import { useActiveVerificationStore } from "@/stores/active-verification-store";

const verificationSchema = z.object({
  target: z.string().trim().min(1, "Enter a claim.").max(12000),
  researchDepth: z.enum(["QUICK", "STANDARD", "DEEP"]),
});

type VerificationFormValues = z.infer<typeof verificationSchema>;
type VerificationCreateResponse = { run_id: string; status: "QUEUED"; events_url: string };

export function VerifyForm() {
  const router = useRouter();
  const { user } = useFirebaseAuth();
  const resumeVerification = useActiveVerificationStore((state) => state.resume);
  const [apiError, setApiError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<VerificationFormValues>({
    resolver: zodResolver(verificationSchema),
    defaultValues: { researchDepth: "STANDARD", target: "" },
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle>New verification</CardTitle>
      </CardHeader>
      <CardContent>
        <form
          className="grid gap-4"
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
          <label className="grid gap-1 text-sm font-medium">
            Research depth
            <Select {...register("researchDepth")}>
              <option value="QUICK">Quick</option>
              <option value="STANDARD">Standard</option>
              <option value="DEEP">Deep</option>
            </Select>
          </label>
          <label className="grid gap-1 text-sm font-medium" htmlFor="verification-target">
            Claim
            <Textarea
              {...register("target")}
              id="verification-target"
              placeholder="Paste the exact claim."
              aria-invalid={Boolean(errors.target)}
              aria-describedby={errors.target ? "verification-target-error" : undefined}
            />
            {errors.target && <span id="verification-target-error" className="text-xs text-destructive">{errors.target.message}</span>}
          </label>
          <div className="flex flex-wrap items-center justify-between gap-3">
            {apiError && <p className="text-xs text-destructive" role="alert">{apiError}</p>}
            <Button type="submit" disabled={isSubmitting}>
              Create verification
              <ArrowRight className="h-4 w-4" aria-hidden="true" />
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
