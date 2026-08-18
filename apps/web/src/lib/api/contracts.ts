import type { components, paths } from "./generated/schema";

export type ApiSchema<Name extends keyof components["schemas"]> = components["schemas"][Name];
export type ApiPath = keyof paths;

export type ConsentView = ApiSchema<"ConsentView">;
export type ConsentSubmission = ApiSchema<"ConsentSubmission">;
export type DeleteAccountRequest = ApiSchema<"DeleteAccountRequest">;
export type DemographicsPatch = ApiSchema<"DemographicsPatch">;
export type EfficacySubmission = ApiSchema<"EfficacySubmission">;
export type EfficacyView = ApiSchema<"EfficacyView">;
export type ErrorEnvelope = ApiSchema<"ErrorEnvelope">;
export type JobAccepted = ApiSchema<"JobAccepted">;
export type ProfileView = ApiSchema<"ProfileView">;
export type QuestionnaireSubmission = ApiSchema<"QuestionnaireSubmission">;
export type QuestionnaireVersionView = ApiSchema<"QuestionnaireVersionView">;
export type ReadResult = ApiSchema<"ReadResult">;
export type ReadSessionView = ApiSchema<"ReadSessionView">;
export type ShareCardCreate = ApiSchema<"ShareCardCreate">;
export type ShareCardJobAccepted = ApiSchema<"ShareCardJobAccepted">;
export type ShareCardView = ApiSchema<"ShareCardView">;
export type UserView = ApiSchema<"UserView">;
export type VoteView = ApiSchema<"VoteView">;

export type ApiRole = ApiSchema<"Role">;
export type Role = Lowercase<ApiRole> | "guest";

export function normalizeRole(role: ApiRole | undefined): Role {
  return role ? role.toLowerCase() as Lowercase<ApiRole> : "guest";
}
