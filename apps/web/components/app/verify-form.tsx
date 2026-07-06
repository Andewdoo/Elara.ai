"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { ArrowRight, FileText, Link2, MessageSquareQuote } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import { useFirebaseAuth } from "@/components/providers/firebase-auth-provider";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input, Select, Textarea } from "@/components/ui/form-controls";
import { apiErrorMessage, authenticatedApiFetch } from "@/lib/auth";

const verificationSchema = z
  .object({
    inputType: z.enum(["CLAIM", "ARTICLE_URL", "ARTICLE_TEXT", "QUOTE", "PARAPHRASE"]),
    target: z.string().trim().min(1, "Enter a claim, URL, text, quote, or document note.").max(12000),
    speaker: z.string().trim().max(160).optional(),
    researchDepth: z.enum(["QUICK", "STANDARD", "DEEP"]),
  })
  .superRefine((value, ctx) => {
    if (value.inputType === "ARTICLE_URL") {
      const parsed = z.string().url().safeParse(value.target);
      if (!parsed.success) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["target"],
          message: "Enter a valid article URL for URL mode.",
        });
      }
    }
    if (value.inputType === "QUOTE" && !value.speaker) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["speaker"],
        message: "Add the named speaker when verifying a quote.",
      });
    }
  });

type VerificationFormValues = z.infer<typeof verificationSchema>;

const inputTypes = [
  { value: "CLAIM", label: "Claim", icon: FileText },
  { value: "ARTICLE_URL", label: "Article URL", icon: Link2 },
  { value: "ARTICLE_TEXT", label: "Pasted article", icon: FileText },
  { value: "QUOTE", label: "Quote", icon: MessageSquareQuote },
  { value: "PARAPHRASE", label: "Paraphrase", icon: MessageSquareQuote },
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
                ...(values.inputType === "ARTICLE_URL"
                  ? { url: values.target }
                  : values.inputType === "QUOTE"
                    ? { quote: values.target, speaker: values.speaker || undefined }
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
            Target
            <Textarea
              {...register("target")}
              id="verification-target"
              placeholder={inputType === "ARTICLE_URL" ? "https://example.com/article" : "Paste the exact claim, quote, article text, or document note."}
              aria-invalid={Boolean(errors.target)}
              aria-describedby={errors.target ? "verification-target-error" : undefined}
            />
            {errors.target && <span id="verification-target-error" className="text-xs text-destructive">{errors.target.message}</span>}
          </label>
          <label className="grid gap-1 text-sm font-medium" htmlFor="verification-speaker">
            Speaker or source context
            <Input id="verification-speaker" {...register("speaker")} placeholder="Optional unless verifying a quote" aria-invalid={Boolean(errors.speaker)} aria-describedby={errors.speaker ? "verification-speaker-error" : undefined}/>
            {errors.speaker && <span id="verification-speaker-error" className="text-xs text-destructive">{errors.speaker.message}</span>}
          </label>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-xs text-muted-foreground">
              FastAPI performs final validation and durably queues the verification.
            </p>
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
