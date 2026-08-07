import type { DetectionRequest } from "../../api/DetectionRequest";
import type { Feature } from "../../domain/Feature";

export interface FeatureDetector {
    detect(request: DetectionRequest): readonly Feature[];
}