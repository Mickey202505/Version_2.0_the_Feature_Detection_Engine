import type { DetectionRequest } from "./DetectionRequest";
import type { DetectionResult } from "./DetectionResult";
import { FeatureDetectionEngineImpl } from "../application/FeatureDetectionEngineImpl";

export class FeatureDetectionEngine {
    private readonly implementation: FeatureDetectionEngineImpl;

    public constructor() {
        this.implementation = new FeatureDetectionEngineImpl();
    }

    public detect(request: DetectionRequest): DetectionResult {
        return this.implementation.detect(request);
    }
}