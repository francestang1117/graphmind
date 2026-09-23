import { describe, expect, it } from "vitest";
import {
  ApplicationUpdateIncompleteError,
  validateMedicalRuntimeHeaders,
} from "../services/runtimeVersion";

const currentHeaders = {
  "x-graphmind-backend-commit": "abc123",
  "x-graphmind-parser-version": "document-parser-pdf-readable-v6",
  "x-graphmind-analysis-pipeline": "medical-insights-readable-v6",
  "x-graphmind-insight-contract": "medical-insights-readable-v6",
  "x-graphmind-analysis-model": "extractive-v3",
};

describe("medical runtime version gate", () => {
  it("accepts a backend with the current parser and analysis contract", () => {
    expect(validateMedicalRuntimeHeaders(currentHeaders)).toMatchObject({
      backendCommit: "abc123",
      parserVersion: "document-parser-pdf-readable-v6",
      analysisPipelineVersion: "medical-insights-readable-v6",
      analysisModel: "extractive-v3",
    });
  });

  it("rejects missing headers and old analysis versions", () => {
    expect(() => validateMedicalRuntimeHeaders({})).toThrow(ApplicationUpdateIncompleteError);
    expect(() => validateMedicalRuntimeHeaders({
      ...currentHeaders,
      "x-graphmind-analysis-pipeline": "medical-insights-readable-v1",
    })).toThrow(ApplicationUpdateIncompleteError);
  });

  it("rejects an older local extractive model identity", () => {
    expect(() => validateMedicalRuntimeHeaders({
      ...currentHeaders,
      "x-graphmind-analysis-model": "extractive-v1",
    })).toThrow(ApplicationUpdateIncompleteError);
  });
});
