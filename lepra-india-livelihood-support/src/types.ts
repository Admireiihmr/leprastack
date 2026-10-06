/**
 * Types & Interfaces for LEPRA Society Livelihood Support Platform
 */

export type BeneficiaryType = 'Individual' | 'Group';

export type DiseaseType = 'Leprosy' | 'Leptospirosis' | 'LF' | 'HIV/AIDS';

export type TreatmentStatus = 'Completed' | 'Under Treatment' | 'Rehabilitation';

export type ApplicationStatus = 
  | 'Pending Eligibility Review' 
  | 'Approved' 
  | 'Disbursed' 
  | 'Verification Pending' 
  | 'Verified Active' 
  | 'Rejected';

export interface PaymentRecord {
  id: string;
  installmentIndex: number;
  amount: number;
  datePaid: string;
  receiptNumber: string;
  loggedBy: string;
  notes?: string;
  proofUrl?: string; // Base64 or URL image supporting JPG
}

export interface EMIScheduleItem {
  index: number; // 1-indexed
  dueDate: string;
  promisedAmount: number;
  amountPaid: number;
  status: 'Pending' | 'Paid' | 'Overdue' | 'Adjusted';
  notes?: string;
}

export interface VerificationDetails {
  latitude?: number;
  longitude?: number;
  photoUrl?: string;
  verifiedAt?: string;
  agentComment?: string;
  isCompleted: boolean;
}

/* ---- Lymphatic Filariasis (LF) impairment / limitation indicators ---- */
export type LFDiseaseGrade = 'Not Assessed' | 'Grade 1' | 'Grade 2' | 'Grade 3' | 'Grade 4';
export type LFMobilityStatus = 'Normal Mobility' | 'Reduced Mobility' | 'Immobile';
export type LFAttackFrequency = 'None' | 'Rare (1-2 / year)' | 'Occasional (3-5 / year)' | 'Frequent (> 5 / year)';

export interface LFIndicators {
  diseaseGrade: LFDiseaseGrade;            // Grade of Disease (lymphoedema staging)
  mobilityStatus: LFMobilityStatus;        // Reduced mobility / immobility status
  acuteAttackFrequency: LFAttackFrequency; // Frequency of acute attacks (ADLA episodes)
  entryLesionsPresent: boolean;            // Presence of entry lesions
  notes?: string;
}

/* ---- HIV/AIDS & High-Risk Group (HRG) vulnerability indicators ---- */
// HRG members are vulnerable to HIV but not necessarily HIV-positive, so
// HRG status and HIV status are tracked as separate, independent fields.
export type HrgType = 'FSW' | 'MSM' | 'IDU';

export interface HIVIndicators {
  isHrgMember: boolean;          // Member of a High-Risk Group
  hrgType?: HrgType;             // FSW / MSM / IDU, present when isHrgMember is true
  isLivingWithHiv: boolean;      // Currently living with HIV
  yearOfDiagnosis?: number;      // Year of HIV detection/diagnosis, present when isLivingWithHiv is true
  onArt: boolean;                // Currently taking ART, present when isLivingWithHiv is true
  artDuration?: string;          // Duration of ART (e.g. "2 years"), present when onArt is true
  practicesSafeSex: boolean;     // Practises safe sex with partner/customer
  notes?: string;
}

/* ---- Social Welfare Scheme convergence tracking ---- */
export interface WelfareScheme {
  id: string;
  schemeName: string;          // e.g. Disability Pension, MGNREGA, Ayushman Bharat
  dateOfLinkage: string;       // ISO date when beneficiary was linked
  benefitType: string;         // Type of benefit received (Pension / Ration / Housing ...)
  monetaryValue?: number;      // Monetary value in INR where applicable
  nonMonetarySupport?: string; // Any other non-monetary support availed
  loggedBy?: string;
  notes?: string;
}

/* ---- Individual member details captured for a Group beneficiary ---- */
export interface GroupMemberDetail {
  name: string;
  age: number;
  gender: 'Male' | 'Female' | 'Other' | 'N/A';
  contactNumber: string;
  // Each group member may carry a distinct diagnosis (leprosy/LF), so health
  // status is captured per-member rather than once for the whole group.
  diseaseType: DiseaseType;
  diagnosisYear: number;
  treatmentStatus: TreatmentStatus;
  physicalLimitations: string[];
  lfIndicators?: LFIndicators;   // present when diseaseType === 'LF'
  hivIndicators?: HIVIndicators; // present when diseaseType === 'HIV/AIDS'
}

/* ---- Guarantor / Co-applicant details (recovery safeguard) ---- */
export interface Guarantor {
  name: string;
  relationship: string;        // relationship to the beneficiary
  contactNumber: string;
  address?: string;
  idProof?: string;            // optional ID reference (Aadhaar last 4 / voter id etc.)
}

export interface Beneficiary {
  id: string;
  // Basic Demographic Details
  type: BeneficiaryType;
  name: string; // Beneficiary name or Group name
  groupName?: string; // Optional if individual, required if group
  groupMembersCount?: number; // Count of members if group
  groupMembers?: GroupMemberDetail[]; // Per-member name/age/gender/contact, one entry per groupMembersCount
  contactNumber: string;
  gender: 'Male' | 'Female' | 'Other' | 'N/A';
  age: number; // Avg age or individual age
  address: string;
  district: string;
  state: string;
  projectName?: string;    // Project under which the beneficiary is registered, powers Project-wise reporting
  fundingPartner?: string; // Donor / funding partner (e.g. Kind Cares)

  // Health Status Details
  diseaseType: DiseaseType;
  diagnosisYear: number;
  treatmentStatus: TreatmentStatus;
  physicalLimitations: string[]; // Options e.g. Hand, Foot, Vision, None
  lfIndicators?: LFIndicators;   // LF-specific impairment metrics (when diseaseType === 'LF')
  hivIndicators?: HIVIndicators; // HIV/HRG-specific metrics (when diseaseType === 'HIV/AIDS')

  // Business Plan Details
  businessName: string;
  businessSector: string; // e.g. Tailoring, Petty Shop, Goat Farming, Tea Stall, Poultry
  requestedAmount: number; // INR
  businessDescription: string;
  expectedMonthlyRevenue: number; // Expected revenue INR

  // Admin Verification & Repayment Planning
  status: ApplicationStatus;
  registeredAt: string;
  registeredByAgent: string;
  
  // Post-Approval terms
  approvedAmount?: number;
  approvalDate?: string;
  repaymentTermMonths?: number; // e.g. 10 or 12 months
  monthlyRepaymentEMI?: number; // Computed SOP EMI
  emiSchedule: EMIScheduleItem[];
  payments: PaymentRecord[];

  // Geo-tagging and post-disbursement verification
  verification?: VerificationDetails;
  disbursementDate?: string;
  rejectionReason?: string;

  // Proof of Business Establishment & early geo-tagging
  businessEstablishmentPhotoUrl?: string; // proof of establishment JPG/Image
  establishmentLatitude?: number;
  establishmentLongitude?: number;

  // Convergence & recovery safeguard additions
  welfareSchemes?: WelfareScheme[]; // Linked social welfare schemes
  guarantor?: Guarantor;            // Guarantor / co-applicant details

  // True for beneficiaries added directly from the Welfare Schemes module who only
  // receive a government scheme linkage and never go through the livelihood
  // Secure Intake Form / loan approval pipeline (no business plan, no SOP recovery).
  isWelfareOnly?: boolean;
}

export interface Notification {
  id: string;
  type: 'info' | 'success' | 'warning' | 'error';
  title: string;
  message: string;
  timestamp: string;
  read: boolean;
  targetRole: 'Admin' | 'Agent';
}
