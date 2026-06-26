"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { ArrowRight, FileText, Link2, MessageSquareQuote, Upload } from "lucide-react";
import { useRouter } from "next/navigation";
import { useForm, useWatch } from "react-hook-form";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input, Select, Textarea } from "@/components/ui/form-controls";
import { mockedRunId } from "@/lib/mock-report";

const verificationSchema = z
  .object({
    inputType: z.enum(["CLAIM", "ARTICLE_URL", "ARTICLE_TEXT", "QUOTE", "PARAPHRASE", "UPLOADED_DOCUMENT"]),
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
  { value: "UPLOADED_DOCUMENT", label: "Document note", icon: Upload },
] as const;

export function VerifyForm() {
  const router = useRouter();
  const {
    register,
    control,
    handleSubmit,
    formState: { errors },
  } = useForm<VerificationFormValues>({
    resolver: zodResolver(verificationSchema),
    defaultValues: {
      inputType: "CLAIM",
      researchDepth: "STANDARD",
      target:
        "Citywide transit ridership rose 35 percent last month because the fare-free pilot brought riders back.",
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
          onSubmit={handleSubmit(() => {
            router.push(`/verify/${mockedRunId}`);
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
          <label className="grid gap-1 text-sm font-medium">
            Target
            <Textarea
              {...register("target")}
              placeholder={inputType === "ARTICLE_URL" ? "https://example.com/article" : "Paste the exact claim, quote, article text, or document note."}
            />
            {errors.target && <span className="text-xs text-destructive">{errors.target.message}</span>}
          </label>
          <label className="grid gap-1 text-sm font-medium">
            Speaker or source context
            <Input {...register("speaker")} placeholder="Optional unless verifying a quote" />
            {errors.speaker && <span className="text-xs text-destructive">{errors.speaker.message}</span>}
          </label>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-xs text-muted-foreground">
              This mock shell validates client-side only. FastAPI remains the final validation and run-creation authority.
            </p>
            <Button type="submit">
              Start mocked run
              <ArrowRight className="h-4 w-4" aria-hidden="true" />
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
