/**
 * Minimal FHIR (R4) representation of a Beneficiary, built for interoperability
 * with external health systems. This is a derived, read-oriented view — the
 * Beneficiary record in src/types.ts / DB_PATHS.beneficiaries remains the
 * single source of truth for the app's own forms and dashboards.
 *
 * Kept as a single flat Patient resource per beneficiary (condition(s) embedded
 * via FHIR's standard "contained" mechanism) rather than a Bundle, so each
 * node under DB_PATHS.beneficiariesFhir stays a simple one-object record.
 */
import { Beneficiary, DiseaseType, GroupMemberDetail, TreatmentStatus } from './types';

export interface FhirCodeableConcept {
  text?: string;
}

export interface FhirCondition {
  resourceType: 'Condition';
  id: string;
  code: FhirCodeableConcept;
  clinicalStatus: FhirCodeableConcept;
  onsetString?: string;
  note?: { text: string }[];
}

export interface FhirPatient {
  resourceType: 'Patient';
  id: string;
  name: { text: string }[];
  gender: 'male' | 'female' | 'other' | 'unknown';
  telecom?: { system: 'phone'; value: string }[];
  address?: { text: string; district?: string; state?: string }[];
  extension?: { url: string; valueInteger?: number }[];
  contained: FhirCondition[];
}

const GENDER_MAP: Record<Beneficiary['gender'], FhirPatient['gender']> = {
  Male: 'male',
  Female: 'female',
  Other: 'other',
  'N/A': 'unknown'
};

const CLINICAL_STATUS_MAP: Record<TreatmentStatus, string> = {
  Completed: 'resolved',
  'Under Treatment': 'active',
  Rehabilitation: 'active'
};

const AGE_EXTENSION_URL = 'https://lepra-india-livelihood-support/fhir/StructureDefinition/age';

function buildCondition(
  conditionId: string,
  diseaseType: DiseaseType,
  diagnosisYear: number,
  treatmentStatus: TreatmentStatus,
  physicalLimitations: string[]
): FhirCondition {
  return {
    resourceType: 'Condition',
    id: conditionId,
    code: { text: diseaseType },
    clinicalStatus: { text: CLINICAL_STATUS_MAP[treatmentStatus] },
    onsetString: String(diagnosisYear),
    note: physicalLimitations.length ? [{ text: physicalLimitations.join(', ') }] : undefined
  };
}

/**
 * Builds a single FHIR Patient resource (with Condition(s) embedded via
 * "contained") from a Beneficiary. Group beneficiaries get one contained
 * Condition per group member.
 */
export function beneficiaryToFhirPatient(id: string, ben: Beneficiary): FhirPatient {
  const contained: FhirCondition[] =
    ben.type === 'Group' && ben.groupMembers?.length
      ? ben.groupMembers.map((member: GroupMemberDetail, index: number) =>
          buildCondition(
            `condition-${index}`,
            member.diseaseType,
            member.diagnosisYear,
            member.treatmentStatus,
            member.physicalLimitations
          )
        )
      : [buildCondition('condition', ben.diseaseType, ben.diagnosisYear, ben.treatmentStatus, ben.physicalLimitations)];

  return {
    resourceType: 'Patient',
    id,
    name: [{ text: ben.name }],
    gender: GENDER_MAP[ben.gender] || 'unknown',
    telecom: ben.contactNumber ? [{ system: 'phone', value: ben.contactNumber }] : undefined,
    address: ben.address
      ? [{ text: ben.address, district: ben.district, state: ben.state }]
      : undefined,
    extension: [{ url: AGE_EXTENSION_URL, valueInteger: ben.age }],
    contained
  };
}
