"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { ArrowRight, FileText } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import { useFirebaseAuth } from "@/components/providers/firebase-auth-provider";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Select, Textarea } from "@/components/ui/form-controls";
import { apiErrorMessage, authenticatedApiFetch } from "@/lib/auth";

const verificationSchema = z
  .object({
    inputType: z.enum(["CLAIM", "ARTICLE_TITLE"]),
    target: z.string().trim().min(1, "Enter a claim or article title.").max(12000),
    researchDepth: z.enum(["QUICK", "STANDARD", "DEEP"]),
  })
  .superRefine((value, ctx) => {
    if (value.inputType === "ARTICLE_TITLE") {
      if (value.target.length > 500) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["target"],
          message: "Keep the article title to 500 characters or fewer.",
        });
      }
    }
  });

type VerificationFormValues = z.infer<typeof verificationSchema>;

const inputTypes = [
  { value: "CLAIM", label: "Claim", icon: FileText },
  { value: "ARTICLE_TITLE", label: "Article title", icon: FileText },
] as const;

type VerificationCreateResponse = { run_id: string; status: "QUEUED"; events_url: string };

export function VerifyForm() {
  const router = useRouter();
  const { user } = useFirebaseAuth();
  const [apiError, setApiError] = useState<string | null>(null);
  const {
    register,
    control,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<VerificationFormValues>({
    resolver: zodResolver(verificationSchema),
    defaultValues: {
      inputType: "CLAIM",
      researchDepth: "STANDARD",
      target: "",
    },
  });

  const inputType = useWatch({ control, name: "inputType" });

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
                input_type: values.inputType,
                research_depth: values.researchDepth,
                ...(values.inputType === "ARTICLE_TITLE"
                  ? { article_title: values.target }
                  : { text: values.target }),
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
              router.push(`/verify/${created.run_id}`);
            } catch (error) {
              setApiError(error instanceof Error ? error.message : "Could not reach the verification API.");
            }
          })}
        >
          <div className="grid gap-2 md:grid-cols-3">
            <label className="grid gap-1 text-sm font-medium md:col-span-2">
              Input type
              <Select {...register("inputType")}>
                {inputTypes.map((item) => (
                  <option key={item.value} value={item.value}>
                    {item.label}
                  </option>
                ))}
                <option value="RESEARCH" disabled>
                  Research — Coming soon
                </option>
              </Select>
            </label>
            <label className="grid gap-1 text-sm font-medium">
              Research depth
              <Select {...register("researchDepth")}>
                <option value="QUICK">Quick</option>
                <option value="STANDARD">Standard</option>
                <option value="DEEP">Deep</option>
              </Select>
            </label>
          </div>
          <label className="grid gap-1 text-sm font-medium" htmlFor="verification-target">
            {inputType === "ARTICLE_TITLE" ? "Article title" : "Target"}
            <Textarea
              {...register("target")}
              id="verification-target"
              placeholder={inputType === "ARTICLE_TITLE" ? "Paste the article headline exactly as it appears in search results." : "Paste the exact claim."}
              aria-invalid={Boolean(errors.target)}
              aria-describedby={errors.target ? "verification-target-error" : undefined}
            />
            {errors.target && <span id="verification-target-error" className="text-xs text-destructive">{errors.target.message}</span>}
          </label>
          {inputType === "ARTICLE_TITLE" && (
            <p className="-mt-2 text-xs text-muted-foreground">
              Elara searches Brave for this title, so it does not depend on the URL used by Google or another search engine.
            </p>
          )}
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
