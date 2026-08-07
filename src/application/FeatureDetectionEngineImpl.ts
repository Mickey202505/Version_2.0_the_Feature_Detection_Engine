import type { DetectionRequest } from "../api/DetectionRequest";
import type { DetectionResult } from "../api/DetectionResult";
import { GreenDetector } from "./detectors/GreenDetector";
import { DetectionPipeline } from "./pipeline/DetectionPipeline";

export class FeatureDetectionEngineImpl {
    private readonly pipeline: DetectionPipeline;

    public constructor() {
        this.pipeline = new DetectionPipeline([
            new GreenDetector()
        ]);
    }

    public detect(request: DetectionRequest): DetectionResult {
        return {
            features: this.pipeline.detect(request)
        };
    }
}