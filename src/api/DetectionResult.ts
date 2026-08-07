import type { Feature } from "../domain/Feature";

export interface DetectionResult {
    readonly features: readonly Feature[];
}