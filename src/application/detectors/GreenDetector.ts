import type { DetectionRequest } from "../../api/DetectionRequest";
import type { Feature } from "../../domain/Feature";
import type { FeatureDetector } from "./FeatureDetector";

export class GreenDetector implements FeatureDetector {
    public detect(_request: DetectionRequest): readonly Feature[] {
        return [];
    }
}