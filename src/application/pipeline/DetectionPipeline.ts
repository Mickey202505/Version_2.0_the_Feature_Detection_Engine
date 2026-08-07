import type { DetectionRequest } from "../../api/DetectionRequest";
import type { Feature } from "../../domain/Feature";
import type { FeatureDetector } from "../detectors/FeatureDetector";

export class DetectionPipeline {
    private readonly detectors: readonly FeatureDetector[];

    public constructor(detectors: readonly FeatureDetector[]) {
        this.detectors = [...detectors];
    }

    public detect(request: DetectionRequest): readonly Feature[] {
        const features: Feature[] = [];

        for (const detector of this.detectors) {
            features.push(...detector.detect(request));
        }

        return features;
    }
}