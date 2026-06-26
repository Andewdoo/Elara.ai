"use client";

import { Bar, BarChart, CartesianGrid, Legend, RadialBar, RadialBarChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import type { ReportRecord } from "@/lib/report-types";

export function ScoreCharts({ report }: { report: ReportRecord }) {
  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <div className="h-72 rounded-lg border bg-white p-3">
        <p className="mb-2 text-sm font-semibold">Score records</p>
        <ResponsiveContainer width="100%" height="88%">
          <RadialBarChart innerRadius="25%" outerRadius="95%" data={report.scoreRecords} startAngle={180} endAngle={-180}>
            <RadialBar dataKey="value" background cornerRadius={4} fill="#0f766e" />
            <Tooltip />
            <Legend iconSize={10} />
          </RadialBarChart>
        </ResponsiveContainer>
      </div>
      <div className="h-72 rounded-lg border bg-white p-3">
        <p className="mb-2 text-sm font-semibold">Evidence balance records</p>
        <ResponsiveContainer width="100%" height="88%">
          <BarChart data={report.evidenceBalanceRecords}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="claimLabel" tick={{ fontSize: 11 }} />
            <YAxis />
            <Tooltip />
            <Legend />
            <Bar dataKey="supportingAdjustedWeight" name="Supporting weight" fill="#0f766e" radius={[4, 4, 0, 0]} />
            <Bar dataKey="contradictingAdjustedWeight" name="Contradicting weight" fill="#be123c" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <div className="h-72 rounded-lg border bg-white p-3">
        <p className="mb-2 text-sm font-semibold">Confidence components</p>
        <ResponsiveContainer width="100%" height="88%">
          <BarChart data={report.confidenceComponentRecords} layout="vertical" margin={{ left: 20 }}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis type="number" domain={[0, 100]} />
            <YAxis type="category" dataKey="label" width={110} tick={{ fontSize: 11 }} />
            <Tooltip />
            <Bar dataKey="value" fill="#2563eb" radius={[0, 4, 4, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <div className="h-72 rounded-lg border bg-white p-3">
        <p className="mb-2 text-sm font-semibold">Research coverage</p>
        <ResponsiveContainer width="100%" height="88%">
          <BarChart data={report.coverageRecords}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="label" tick={{ fontSize: 11 }} />
            <YAxis />
            <Tooltip />
            <Bar dataKey="value" fill="#d97706" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
