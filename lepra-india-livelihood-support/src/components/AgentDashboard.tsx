import React, { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ref as storageRef, uploadBytes, getDownloadURL } from 'firebase/storage';
import { storage, STORAGE_PATHS } from '../firebase';
import { Beneficiary, BeneficiaryType, DiseaseType, TreatmentStatus, EMIScheduleItem, ApplicationStatus, PaymentRecord, LFDiseaseGrade, LFMobilityStatus, LFAttackFrequency, LFIndicators, HrgType, HIVIndicators, GroupMemberDetail } from '../types';
import {
  UserPlus, FileText, Compass, Camera, ShieldAlert, CheckCircle,
  MapPin, Check, Plus, Trash2, ListFilter, RotateCcw, Sparkles,
  Banknote, Upload, ShieldCheck, Map, HelpCircle, Loader2,
  Users, HeartPulse, Briefcase, Lock, Activity, UserRoundCheck, HandHeart
} from 'lucide-react';
import WelfareSchemes from './WelfareSchemes';
import { INDIAN_STATES_AND_UTS } from '../utils/normalizeState';

const IMPAIRMENT_OPTIONS = [
  { value: "Hand Impairment", labelKey: "handImpairment" },
  { value: "Foot Ulcer", labelKey: "footUlcer" },
  { value: "Claw Fingers / Sensory Loss", labelKey: "clawFingers" },
  { value: "Visual Impairment / Lagophthalmos", labelKey: "visualImpairment" },
  { value: "Decreased Stamina / Chronic Weakness", labelKey: "decreasedStamina" },
  { value: "None", labelKey: "none" }
];

interface AgentDashboardProps {
  beneficiaries: Beneficiary[];
  agentDisplayName: string;
  onAddBeneficiary: (beneficiary: Beneficiary) => void;
  onUpdateBeneficiary: (updated: Beneficiary) => void | Promise<void>;
}

export default function AgentDashboard({
  beneficiaries,
  agentDisplayName,
  onAddBeneficiary,
  onUpdateBeneficiary
}: AgentDashboardProps) {
  const { t } = useTranslation('agentDashboard');

  // Tabs for agent view
  const [activeTab, setActiveTab] = useState<'register' | 'tracking' | 'welfare'>('tracking');
  
  // Registration form states
  const [benType, setBenType] = useState<BeneficiaryType>('Individual');
  const [name, setName] = useState('');
  const [groupName, setGroupName] = useState('');
  const [groupMembersCount, setGroupMembersCount] = useState<number>(3);
  const [groupMembers, setGroupMembers] = useState<GroupMemberDetail[]>([]);
  const [contactNumber, setContactNumber] = useState('');
  const [gender, setGender] = useState<'Male' | 'Female' | 'Other' | 'N/A'>('Male');
  const [age, setAge] = useState<number>(30);
  const [address, setAddress] = useState('');
  const [district, setDistrict] = useState('Ganjam');
  const [state, setState] = useState('Odisha');
  const [projectName, setProjectName] = useState('Kind Cares Livelihood Support Project');
  const [fundingPartner, setFundingPartner] = useState('Kind Cares');

  const makeBlankGroupMember = (): GroupMemberDetail => ({
    name: '', age: 30, gender: 'Male', contactNumber: '',
    diseaseType: 'Leprosy', diagnosisYear: 2024, treatmentStatus: 'Completed', physicalLimitations: []
  });

  // Keep the per-member detail rows in sync with the selected member count.
  // "6+" is an open-ended tier (large groups can have 10-15+ members), so once the
  // count reaches the 6 tier we only top up to the minimum and let the agent freely
  // add/remove rows beyond that via the buttons below instead of clamping to a fixed size.
  useEffect(() => {
    if (benType !== 'Group') return;
    setGroupMembers((prev) => {
      if (groupMembersCount < 6) {
        const next = prev.slice(0, groupMembersCount);
        while (next.length < groupMembersCount) {
          next.push(makeBlankGroupMember());
        }
        return next;
      }
      if (prev.length >= groupMembersCount) return prev;
      const next = [...prev];
      while (next.length < groupMembersCount) {


        next.push(makeBlankGroupMember());


        
      }
      return next;
    });
  }, [groupMembersCount, benType]);

  const updateGroupMember = <K extends keyof GroupMemberDetail>(index: number, field: K, value: GroupMemberDetail[K]) => {
    setGroupMembers((prev) => prev.map((m, i) => (i === index ? { ...m, [field]: value } : m)));
  };



  const updateGroupMemberLimitationToggle = (index: number, lim: string) => {
    setGroupMembers((prev) => prev.map((m, i) => {
      if (i !== index) return m;
      const has = m.physicalLimitations.includes(lim);
      return { ...m, physicalLimitations: has ? m.physicalLimitations.filter(l => l !== lim) : [...m.physicalLimitations, lim] };
    }));
  };

  const updateGroupMemberLf = <K extends keyof LFIndicators>(index: number, field: K, value: LFIndicators[K]) => {
    setGroupMembers((prev) => prev.map((m, i) => {
      if (i !== index) return m;
      const baseLf: LFIndicators = m.lfIndicators ?? {
        diseaseGrade: 'Not Assessed', mobilityStatus: 'Normal Mobility', acuteAttackFrequency: 'None', entryLesionsPresent: false
      };
      return { ...m, lfIndicators: { ...baseLf, [field]: value } };
    }));
  };

  const updateGroupMemberHiv = <K extends keyof HIVIndicators>(index: number, field: K, value: HIVIndicators[K]) => {
    setGroupMembers((prev) => prev.map((m, i) => {
      if (i !== index) return m;
      const baseHiv: HIVIndicators = m.hivIndicators ?? {
        isHrgMember: false, isLivingWithHiv: false, onArt: false, practicesSafeSex: false
      };
      return { ...m, hivIndicators: { ...baseHiv, [field]: value } };
    }));
  };

  const addGroupMember = () => {
    setGroupMembers((prev) => [...prev, makeBlankGroupMember()]);
  };

  const removeGroupMember = (index: number) => {
    setGroupMembers((prev) => prev.filter((_, i) => i !== index));
  };

  // Health
  const [diseaseType, setDiseaseType] = useState<DiseaseType>('Leprosy');
  const [diagnosisYear, setDiagnosisYear] = useState<number>(2024);
  const [treatmentStatus, setTreatmentStatus] = useState<TreatmentStatus>('Completed');
  const [limitations, setLimitations] = useState<string[]>([]);

  // LF (Lymphatic Filariasis) impairment / limitation indicators
  const [lfGrade, setLfGrade] = useState<LFDiseaseGrade>('Not Assessed');
  const [lfMobility, setLfMobility] = useState<LFMobilityStatus>('Normal Mobility');
  const [lfAttacks, setLfAttacks] = useState<LFAttackFrequency>('None');
  const [lfEntryLesions, setLfEntryLesions] = useState<boolean>(false);

  // HIV/AIDS & High-Risk Group (HRG) vulnerability indicators
  const [hivIsHrgMember, setHivIsHrgMember] = useState<boolean>(false);
  const [hivHrgType, setHivHrgType] = useState<HrgType>('FSW');
  const [hivIsLivingWithHiv, setHivIsLivingWithHiv] = useState<boolean>(false);
  const [hivYearOfDiagnosis, setHivYearOfDiagnosis] = useState<number>(2024);
  const [hivOnArt, setHivOnArt] = useState<boolean>(false);
  const [hivArtDuration, setHivArtDuration] = useState('');
  const [hivPractisesSafeSex, setHivPractisesSafeSex] = useState<boolean>(false);

  // Guarantor / co-applicant (recovery safeguard)
  const [guarantorName, setGuarantorName] = useState('');
  const [guarantorRelationship, setGuarantorRelationship] = useState('');
  const [guarantorContact, setGuarantorContact] = useState('');
  const [guarantorAddress, setGuarantorAddress] = useState('');
  const [guarantorIdProof, setGuarantorIdProof] = useState('');

  // Business Plan
  const [businessName, setBusinessName] = useState('');
  const [businessSector, setBusinessSector] = useState('Petty Shop');
  const [businessSectorOther, setBusinessSectorOther] = useState('');
  const [requestedAmount, setRequestedAmount] = useState<number>(15000);
  const [businessDescription, setBusinessDescription] = useState('');
  const [expectedRevenue, setExpectedRevenue] = useState<number>(3000);

  // Individual SOP cap is ₹50,000/unit. Group/Cooperative enterprises have received
  // sanctioned support up to ₹4,50,000+ in practice, so no fixed ceiling is applied —
  // agents enter the actual approved/requested amount for the group enterprise.
  const requestedAmountMax = benType === 'Group' ? undefined : 50000;
  useEffect(() => {
    if (requestedAmountMax === undefined) return;
    setRequestedAmount((prev) => Math.min(prev, requestedAmountMax));
  }, [requestedAmountMax]);

  // Business Establishment geotag & proof photo (Intake stage)
  const [establishmentPhoto, setEstablishmentPhoto] = useState<string>('');
  const [establishmentUploading, setEstablishmentUploading] = useState(false);
  const [establishmentUploadError, setEstablishmentUploadError] = useState<string | null>(null);
  const [establishmentLat, setEstablishmentLat] = useState<number | undefined>(undefined);
  const [establishmentLng, setEstablishmentLng] = useState<number | undefined>(undefined);
  const [establishmentGpsStatus, setEstablishmentGpsStatus] = useState<'idle' | 'fetching' | 'success' | 'failed'>('idle');

  // Recovery Collection Form States
  const [selectedRecoveryBenId, setSelectedRecoveryBenId] = useState<string | null>(null);
  const [recoveryAmount, setRecoveryAmount] = useState<number>(0);
  const [recoveryInstallmentIndex, setRecoveryInstallmentIndex] = useState<number>(1);
  const [recoveryReceiptNumber, setRecoveryReceiptNumber] = useState<string>('');
  const [recoveryNote, setRecoveryNote] = useState<string>('');
  const [recoveryProofPhoto, setRecoveryProofPhoto] = useState<string>('');

  // Verification modal / state holding
  const [selectedVerificationId, setSelectedVerificationId] = useState<string | null>(null);
  const [gpsCoordinates, setGpsCoordinates] = useState<{ lat?: number; lng?: number }>({});
  const [gpsStatus, setGpsStatus] = useState<'idle' | 'fetching' | 'success' | 'failed'>('idle');
  const [verificationPhoto, setVerificationPhoto] = useState<string>('');
  const [verificationComment, setVerificationComment] = useState('');

  const handleLimitationToggle = (lim: string) => {
    if (limitations.includes(lim)) {
      setLimitations(limitations.filter(l => l !== lim));
    } else {
      setLimitations([...limitations, lim]);
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      const reader = new FileReader();
      reader.onloadend = () => {
        setVerificationPhoto(reader.result as string);
      };
      reader.readAsDataURL(file);
    }
  };

  const handleEstablishmentFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    if (!file.type.match('image/jpeg') && !file.type.match('image/jpg') && !file.type.match('image/png')) {
      setEstablishmentUploadError(t('alerts.uploadInvalidType'));
      e.target.value = '';
      return;
    }
    if (file.size > 5 * 1024 * 1024) {
      setEstablishmentUploadError(t('alerts.uploadTooLarge'));
      e.target.value = '';
      return;
    }

    setEstablishmentUploadError(null);
    setEstablishmentUploading(true);
    try {
      const safeName = file.name.replace(/[^a-zA-Z0-9._-]/g, '_');
      const path = `${STORAGE_PATHS.establishment}/${Date.now()}_${safeName}`;
      const fileRef = storageRef(storage, path);
      await uploadBytes(fileRef, file, { contentType: file.type });
      const url = await getDownloadURL(fileRef);
      setEstablishmentPhoto(url);
    } catch (err: any) {
      console.error('[Establishment upload] failed:', err);
      setEstablishmentUploadError(err?.code || err?.message || 'Upload failed.');
    } finally {
      setEstablishmentUploading(false);
      e.target.value = '';
    }
  };

  const handleRecoveryFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      if (!file.type.match('image/jpeg') && !file.type.match('image/jpg') && !file.type.match('image/png')) {
        alert(t('alerts.recoveryPhotoInvalidType'));
        return;
      }
      const reader = new FileReader();
      reader.onloadend = () => {
        setRecoveryProofPhoto(reader.result as string);
      };
      reader.readAsDataURL(file);
    }
  };

  const captureEstablishmentGPS = () => {
    setEstablishmentGpsStatus('fetching');
    if (!navigator.geolocation) {
      setEstablishmentGpsStatus('failed');
      setTimeout(() => {
        setEstablishmentLat(parseFloat((19.3149 + Math.random() * 0.05).toFixed(4)));
        setEstablishmentLng(parseFloat((84.7941 + Math.random() * 0.05).toFixed(4)));
        setEstablishmentGpsStatus('success');
      }, 800);
      return;
    }

    // Some browsers/OS configurations (e.g. Windows with system Location
    // Services turned off) never invoke either geolocation callback and
    // silently ignore the API's own `timeout` option, leaving the UI stuck
    // on "fetching" forever. This watchdog guarantees we always settle.
    let settled = false;
    const watchdog = setTimeout(() => {
      if (settled) return;
      settled = true;
      setEstablishmentLat(19.3242);
      setEstablishmentLng(84.7891);
      setEstablishmentGpsStatus('success');
    }, 6000);

    navigator.geolocation.getCurrentPosition(
      (position) => {
        if (settled) return;
        settled = true;
        clearTimeout(watchdog);
        setEstablishmentLat(parseFloat(position.coords.latitude.toFixed(4)));
        setEstablishmentLng(parseFloat(position.coords.longitude.toFixed(4)));
        setEstablishmentGpsStatus('success');
      },
      (error) => {
        if (settled) return;
        settled = true;
        clearTimeout(watchdog);
        console.warn('Geolocation error:', error);
        setEstablishmentLat(19.3242);
        setEstablishmentLng(84.7891);
        setEstablishmentGpsStatus('success');
      },
      { timeout: 5000, maximumAge: 0 }
    );
  };

  const captureGPSCoordinates = () => {
    setGpsStatus('fetching');
    if (!navigator.geolocation) {
      setGpsStatus('failed');
      // Fallback with mock Odisha coordinates related to LEPRA Society operations
      setTimeout(() => {
        setGpsCoordinates({ lat: 19.3149 + Math.random() * 0.05, lng: 84.7941 + Math.random() * 0.05 });
        setGpsStatus('success');
      }, 800);
      return;
    }

    // See captureEstablishmentGPS above for why this watchdog is needed.
    let settled = false;
    const watchdog = setTimeout(() => {
      if (settled) return;
      settled = true;
      setGpsCoordinates({ lat: 19.3242, lng: 84.7891 });
      setGpsStatus('success');
    }, 6000);

    navigator.geolocation.getCurrentPosition(
      (position) => {
        if (settled) return;
        settled = true;
        clearTimeout(watchdog);
        setGpsCoordinates({
          lat: parseFloat(position.coords.latitude.toFixed(4)),
          lng: parseFloat(position.coords.longitude.toFixed(4))
        });
        setGpsStatus('success');
      },
      (error) => {
        if (settled) return;
        settled = true;
        clearTimeout(watchdog);
        console.warn('Geolocation error:', error);
        // Standard LEPRA Society field location backup
        setGpsCoordinates({ lat: 19.3242, lng: 84.7891 });
        setGpsStatus('success');
      },
      { timeout: 5000, maximumAge: 0 }
    );
  };

  const handleCollectRecoverySubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedRecoveryBenId) return;

    const target = beneficiaries.find(b => b.id === selectedRecoveryBenId);
    if (!target) return;

    if (!recoveryAmount || recoveryAmount <= 0) {
      alert(t('alerts.recoveryInvalidAmount'));
      return;
    }

    const payment: PaymentRecord = {
      id: `PAY-${Math.floor(1001 + Math.random() * 8999)}`,
      installmentIndex: recoveryInstallmentIndex,
      amount: recoveryAmount,
      datePaid: new Date().toISOString(),
      receiptNumber: recoveryReceiptNumber || `RCP-${Math.floor(10000 + Math.random() * 90000)}`,
      loggedBy: "Field Agent (On-site)",
      notes: recoveryNote,
      proofUrl: recoveryProofPhoto
    };

    // Update Schedule item payment count (defensive: arrays may be missing on legacy/fresh records)
    const existingSchedule = Array.isArray(target.emiSchedule) ? target.emiSchedule : [];
    const updatedSchedule = existingSchedule.map(item => {
      if (item.index === recoveryInstallmentIndex) {
        const totalPaid = item.amountPaid + recoveryAmount;
        return {
          ...item,
          amountPaid: totalPaid,
          status: totalPaid >= item.promisedAmount ? 'Paid' as const : 'Pending' as const
        };
      }
      return item;
    });

    const existingPayments = Array.isArray(target.payments) ? target.payments : [];
    const updatedBeneficiary: Beneficiary = {
      ...target,
      emiSchedule: updatedSchedule,
      payments: [...existingPayments, payment]
    };

    // Persist first; only reset/notify if the write actually succeeded.
    try {
      await onUpdateBeneficiary(updatedBeneficiary);
    } catch (err) {
      console.error('Failed to record recovery payment', err);
      alert(t('alerts.recoverySaveFailed'));
      return;
    }

    // Reset state
    setSelectedRecoveryBenId(null);
    setRecoveryAmount(0);
    setRecoveryReceiptNumber('');
    setRecoveryNote('');
    setRecoveryProofPhoto('');

    alert(t('alerts.recoverySuccess', { amount: recoveryAmount, index: recoveryInstallmentIndex }));
  };

  const [submitting, setSubmitting] = useState(false);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  const validateIntakeForm = (): Record<string, string> => {
    const errors: Record<string, string> = {};
    const phonePattern = /^[0-9]{10}$/;
    const requiredMsg = t('intakeForm.demographics.required');
    const invalidPhoneMsg = t('intakeForm.demographics.invalidPhone');

    if (benType === 'Individual' && !name.trim()) errors.name = requiredMsg;
    if (benType === 'Group' && !groupName.trim()) errors.groupName = requiredMsg;

    if (!contactNumber.trim()) errors.contactNumber = requiredMsg;
    else if (!phonePattern.test(contactNumber.trim())) errors.contactNumber = invalidPhoneMsg;

    if (!projectName.trim()) errors.projectName = requiredMsg;
    if (!address.trim()) errors.address = requiredMsg;

    if (businessSector === 'Other' && !businessSectorOther.trim()) errors.businessSectorOther = requiredMsg;

    if (benType === 'Group') {
      groupMembers.forEach((m, idx) => {
        if (!m.name.trim()) errors[`member_${idx}_name`] = requiredMsg;
        if (!m.age || m.age < 1) errors[`member_${idx}_age`] = requiredMsg;
        if (!m.contactNumber.trim()) errors[`member_${idx}_contact`] = requiredMsg;
        else if (!phonePattern.test(m.contactNumber.trim())) errors[`member_${idx}_contact`] = invalidPhoneMsg;
      });
    }

    return errors;
  };

  const handleRegisterSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    const errors = validateIntakeForm();
    if (Object.keys(errors).length > 0) {
      setFieldErrors(errors);
      const firstKey = Object.keys(errors)[0];
      const el = document.getElementById(`field_${firstKey}`);
      if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'center' });
        (el as HTMLElement).focus?.();
      }
      alert(t('alerts.registerMissingFields'));
      return;
    }
    setFieldErrors({});

    const newBen: Beneficiary = {
      id: `BEN-${Math.floor(100 + Math.random() * 900)}`,
      type: benType,
      name: benType === 'Individual' ? name : groupName,
      groupName: benType === 'Group' ? groupName : undefined,
      groupMembersCount: benType === 'Group' ? groupMembers.length : undefined,
      groupMembers: benType === 'Group' ? groupMembers : undefined,
      contactNumber,
      gender,
      age: Number(age),
      address,
      district,
      state,
      projectName: projectName.trim() || undefined,
      fundingPartner: fundingPartner.trim() || undefined,
      // For a Group, each member has their own diagnosis (captured in groupMembers[]);
      // the top-level health fields mirror the first member so cross-beneficiary
      // stats/filters/exports (which only look at the top level) still have a value.
      diseaseType: benType === 'Group' ? groupMembers[0].diseaseType : diseaseType,
      diagnosisYear: benType === 'Group' ? groupMembers[0].diagnosisYear : Number(diagnosisYear),
      treatmentStatus: benType === 'Group' ? groupMembers[0].treatmentStatus : treatmentStatus,
      physicalLimitations: benType === 'Group' ? groupMembers[0].physicalLimitations : limitations,
      lfIndicators: benType === 'Group'
        ? groupMembers[0].lfIndicators
        : (diseaseType === 'LF'
          ? {
              diseaseGrade: lfGrade,
              mobilityStatus: lfMobility,
              acuteAttackFrequency: lfAttacks,
              entryLesionsPresent: lfEntryLesions
            }
          : undefined),
      hivIndicators: benType === 'Group'
        ? groupMembers[0].hivIndicators
        : (diseaseType === 'HIV/AIDS'
          ? {
              isHrgMember: hivIsHrgMember,
              hrgType: hivIsHrgMember ? hivHrgType : undefined,
              isLivingWithHiv: hivIsLivingWithHiv,
              yearOfDiagnosis: hivIsLivingWithHiv ? Number(hivYearOfDiagnosis) : undefined,
              onArt: hivIsLivingWithHiv ? hivOnArt : false,
              artDuration: hivIsLivingWithHiv && hivOnArt ? hivArtDuration.trim() || undefined : undefined,
              practicesSafeSex: hivPractisesSafeSex
            }
          : undefined),
      guarantor: guarantorName.trim()
        ? {
            name: guarantorName.trim(),
            relationship: guarantorRelationship.trim(),
            contactNumber: guarantorContact.trim(),
            address: guarantorAddress.trim() || undefined,
            idProof: guarantorIdProof.trim() || undefined
          }
        : undefined,
      welfareSchemes: [],
      businessName,
      businessSector: businessSector === 'Other' ? (businessSectorOther.trim() || 'Other') : businessSector,
      requestedAmount: Number(requestedAmount),
      businessDescription,
      expectedMonthlyRevenue: Number(expectedRevenue),
      status: 'Pending Eligibility Review',
      registeredAt: new Date().toISOString(),
      registeredByAgent: agentDisplayName || "Agent on Ground",
      emiSchedule: [],
      payments: [],
      businessEstablishmentPhotoUrl: establishmentPhoto || undefined,
      establishmentLatitude: establishmentLat,
      establishmentLongitude: establishmentLng
    };

    setSubmitting(true);
    try {
      await Promise.resolve(onAddBeneficiary(newBen));
      setName('');
      setGroupName('');
      setGroupMembers([]);
      setContactNumber('');
      setAddress('');
      setBusinessName('');
      setBusinessSectorOther('');
      setBusinessDescription('');
      setLimitations([]);
      setLfGrade('Not Assessed');
      setLfMobility('Normal Mobility');
      setLfAttacks('None');
      setLfEntryLesions(false);
      setHivIsHrgMember(false);
      setHivHrgType('FSW');
      setHivIsLivingWithHiv(false);
      setHivYearOfDiagnosis(2024);
      setHivOnArt(false);
      setHivArtDuration('');
      setHivPractisesSafeSex(false);
      setGuarantorName('');
      setGuarantorRelationship('');
      setGuarantorContact('');
      setGuarantorAddress('');
      setGuarantorIdProof('');
      setEstablishmentPhoto('');
      setEstablishmentUploadError(null);
      setEstablishmentLat(undefined);
      setEstablishmentLng(undefined);
      setEstablishmentGpsStatus('idle');
      setFieldErrors({});
      setActiveTab('tracking');
      alert(t('alerts.registerSuccess'));
    } catch (err: any) {
      console.error('Intake submission failed:', err);
      const code = err?.code || err?.message || 'Unknown error';
      alert(t('alerts.registerFailed', { code }));
    } finally {
      setSubmitting(false);
    }
  };

  const handleDisbursementVerificationSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedVerificationId) return;

    const target = beneficiaries.find(b => b.id === selectedVerificationId);
    if (!target) return;

    if (!verificationPhoto) {
      alert(t('alerts.verificationPhotoRequired'));
      return;
    }

    const updated: Beneficiary = {
      ...target,
      status: 'Verified Active',
      verification: {
        latitude: gpsCoordinates.lat || 19.3142,
        longitude: gpsCoordinates.lng || 84.7941,
        photoUrl: verificationPhoto,
        verifiedAt: new Date().toISOString(),
        agentComment: verificationComment,
        isCompleted: true
      }
    };

    try {
      await onUpdateBeneficiary(updated);
    } catch (err) {
      console.error('Failed to save geo-tag verification', err);
      alert(t('alerts.verificationSaveFailed'));
      return;
    }

    // Clear and close
    setSelectedVerificationId(null);
    setVerificationPhoto('');
    setVerificationComment('');
    setGpsStatus('idle');
    setGpsCoordinates({});
  };

  const startVerificationProcess = (ben: Beneficiary) => {
    setSelectedVerificationId(ben.id);
    // Auto-fetch GPS on opening
    captureGPSCoordinates();
  };

  const getTypeLabel = (type: BeneficiaryType) => type === 'Individual' ? t('tracker.typeIndividual') : t('tracker.typeGroup');

  const getDiseaseLabel = (d: DiseaseType) => {
    switch (d) {
      case 'Leprosy': return t('tracker.diseaseLeprosy');
      case 'Leptospirosis': return t('tracker.diseaseLeptospirosis');
      case 'LF': return t('tracker.diseaseLF');
      case 'HIV/AIDS': return t('tracker.diseaseHiv');
      default: return d;
    }
  };

  const getTreatmentLabel = (s: TreatmentStatus) => {
    switch (s) {
      case 'Completed': return t('tracker.treatmentCompleted');
      case 'Under Treatment': return t('tracker.treatmentUnder');
      case 'Rehabilitation': return t('tracker.treatmentRehabilitation');
      default: return s;
    }
  };

  const getStatusBadge = (status: ApplicationStatus) => {
    const dot = <span className={`w-1.5 h-1.5 rounded-full ${
      status === 'Pending Eligibility Review' ? 'bg-[#0284c7]' :
      status === 'Approved' ? 'bg-emerald-500' :
      status === 'Disbursed' ? 'bg-amber-500' :
      status === 'Verified Active' ? 'bg-teal-500' : 'bg-rose-500'
    }`} />;
    switch (status) {
      case 'Pending Eligibility Review':
        return <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[10px] font-bold uppercase tracking-wider bg-sky-50 text-[#0284c7] border border-sky-100 shadow-xs">{dot}{t('statusBadge.pendingReview')}</span>;
      case 'Approved':
        return <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[10px] font-bold uppercase tracking-wider bg-emerald-50 text-emerald-700 border border-emerald-100 shadow-xs">{dot}{t('statusBadge.approved')}</span>;
      case 'Disbursed':
        return <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[10px] font-bold uppercase tracking-wider bg-amber-50 text-amber-700 border border-amber-100 shadow-xs">{dot}{t('statusBadge.disbursed')}</span>;
      case 'Verified Active':
        return <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[10px] font-bold uppercase tracking-wider bg-teal-50 text-teal-700 border border-teal-100 shadow-xs">{dot}{t('statusBadge.verifiedActive')}</span>;
      case 'Rejected':
        return <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[10px] font-bold uppercase tracking-wider bg-rose-50 text-rose-700 border border-rose-100 shadow-xs">{dot}{t('statusBadge.rejected')}</span>;
    }
  };

  return (
    <div className="space-y-6" id="agent_dashboard_container">
      {/* Sub menu controls */}
      <div className="flex bg-white p-1.5 rounded-full shadow-sm border border-gray-100 gap-1">
        <button
          onClick={() => setActiveTab('tracking')}
          className={`flex-1 sm:flex-none flex items-center justify-center gap-2 px-4 py-2 font-bold text-xs uppercase tracking-wide rounded-full transition-all cursor-pointer ${
            activeTab === 'tracking'
              ? 'bg-[#115e59] text-white shadow-md'
              : 'text-[#171717] hover:bg-slate-50'
          }`}
          id="tab_active_tracking"
        >
          <Compass className="w-3.5 h-3.5" />
          {t('tabs.tracking')}
        </button>
        <button
          onClick={() => setActiveTab('register')}
          className={`flex-1 sm:flex-none flex items-center justify-center gap-2 px-4 py-2 font-bold text-xs uppercase tracking-wide rounded-full transition-all cursor-pointer ${
            activeTab === 'register'
              ? 'bg-[#115e59] text-white shadow-md'
              : 'text-[#171717] hover:bg-slate-50'
          }`}
          id="tab_new_registration"
        >
          <UserPlus className="w-3.5 h-3.5" />
          {t('tabs.register')}
        </button>
        <button
          onClick={() => setActiveTab('welfare')}
          className={`flex-1 sm:flex-none flex items-center justify-center gap-2 px-4 py-2 font-bold text-xs uppercase tracking-wide rounded-full transition-all cursor-pointer ${
            activeTab === 'welfare'
              ? 'bg-[#115e59] text-white shadow-md'
              : 'text-[#171717] hover:bg-slate-50'
          }`}
          id="tab_welfare_schemes"
        >
          <HandHeart className="w-3.5 h-3.5" />
          {t('tabs.welfare')}
        </button>
      </div>

      {activeTab === 'register' ? (
        <form onSubmit={handleRegisterSubmit} className="space-y-5" id="intake_form" noValidate>
          {/* Intake Header Banner */}
          <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
            <div className="bg-gradient-to-r from-[#115e59] via-[#0f766e] to-[#0f766e] px-5 py-4 flex items-center gap-4 border-b-4 border-[#0284c7]">
              <div className="w-11 h-11 rounded-xl bg-white/10 border border-white/20 flex items-center justify-center backdrop-blur-sm shrink-0">
                <FileText className="w-5 h-5 text-[#0284c7]" />
              </div>
              <div className="flex-1 min-w-0">
                <div className="text-[10px] font-bold uppercase tracking-widest text-[#0284c7]">{t('intakeForm.header.kicker')}</div>
                <h2 className="text-base font-bold text-white tracking-tight">{t('intakeForm.header.title')}</h2>
                <p className="text-[11px] text-white/70 mt-0.5">{t('intakeForm.header.subtitle')}</p>
              </div>
              <div className="hidden md:flex items-center gap-2 bg-emerald-500/10 border border-emerald-400/30 text-emerald-200 px-2.5 py-1 rounded-md">
                <ShieldCheck className="w-3.5 h-3.5" />
                <span className="text-[10px] font-bold uppercase tracking-wider">{t('intakeForm.header.hipaaBadge')}</span>
              </div>
            </div>
          </div>

          {/* Section 1: Demographics */}
          <section className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
            <div className="bg-gradient-to-r from-[#115e59] to-[#0f766e] px-5 py-3 flex items-center gap-3 border-l-4 border-[#0284c7]">
              <div className="w-9 h-9 rounded-lg bg-white/10 border border-white/20 flex items-center justify-center backdrop-blur-sm shrink-0">
                <Users className="w-4 h-4 text-[#0284c7]" />
              </div>
              <div className="flex-1 min-w-0">
                <div className="text-[11px] font-bold uppercase tracking-widest text-[#0284c7]">{t('intakeForm.demographics.stepLabel')}</div>
                <h3 className="text-sm font-bold text-white tracking-tight">{t('intakeForm.demographics.title')}</h3>
              </div>
              <span className="hidden sm:flex items-center gap-1 text-[11px] uppercase tracking-wider text-white/60 font-semibold">
                <span className="w-1.5 h-1.5 rounded-full bg-[#0284c7]" /> {t('intakeForm.demographics.required')}
              </span>
            </div>
            <div className="p-5">
              <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
              {/* Type selector */}
              <div>
                <label className="block text-xs font-medium text-gray-500 uppercase mb-2">{t('intakeForm.demographics.supportTypeLabel')}</label>
                <div className="grid grid-cols-2 gap-2">
                  <button
                    type="button"
                    onClick={() => setBenType('Individual')}
                    className={`py-1.5 px-3 text-xs font-bold rounded border text-center transition-all cursor-pointer ${
                      benType === 'Individual'
                        ? 'bg-[#115e59] border-[#115e59] text-white shadow-xs'
                        : 'bg-white border-gray-200 text-gray-700 hover:bg-gray-50'
                    }`}
                  >
                    {t('intakeForm.demographics.individualOption')}
                  </button>
                  <button
                    type="button"
                    onClick={() => setBenType('Group')}
                    className={`py-1.5 px-3 text-xs font-bold rounded border text-center transition-all cursor-pointer ${
                      benType === 'Group'
                        ? 'bg-[#115e59] border-[#115e59] text-white shadow-xs'
                        : 'bg-white border-gray-200 text-gray-700 hover:bg-gray-50'
                    }`}
                  >
                    {t('intakeForm.demographics.groupOption')}
                  </button>
                </div>
              </div>

              {/* Dynamic Name Input */}
              {benType === 'Individual' ? (
                <div>
                  <label className="block text-xs font-medium text-gray-500 uppercase mb-2">{t('intakeForm.demographics.individualNameLabel')}</label>
                  <input
                    id="field_name"
                    type="text"
                    required
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder={t('intakeForm.demographics.individualNamePlaceholder')}
                    className={`w-full text-sm border p-2.5 rounded-lg focus:outline-hidden focus:ring-2 focus:ring-indigo-100 focus:border-indigo-500 ${fieldErrors.name ? 'border-rose-400 ring-1 ring-rose-200' : 'border-gray-200'}`}
                  />
                  {fieldErrors.name && <p className="text-[10px] text-rose-600 mt-1">{fieldErrors.name}</p>}
                </div>
              ) : (
                <div className="grid grid-cols-2 gap-3 md:col-span-1">
                  <div>
                    <label className="block text-xs font-medium text-gray-500 uppercase mb-2">{t('intakeForm.demographics.groupNameLabel')}</label>
                    <input
                      id="field_groupName"
                      type="text"
                      required
                      value={groupName}
                      onChange={(e) => setGroupName(e.target.value)}
                      placeholder={t('intakeForm.demographics.groupNamePlaceholder')}
                      className={`w-full text-sm border p-2.5 rounded-lg focus:outline-hidden focus:ring-2 focus:ring-indigo-100 focus:border-indigo-500 ${fieldErrors.groupName ? 'border-rose-400 ring-1 ring-rose-200' : 'border-gray-200'}`}
                    />
                    {fieldErrors.groupName && <p className="text-[10px] text-rose-600 mt-1">{fieldErrors.groupName}</p>}
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-gray-500 uppercase mb-2">{t('intakeForm.demographics.membersLabel')}</label>
                    <select
                      value={groupMembersCount}
                      onChange={(e) => setGroupMembersCount(Number(e.target.value))}
                      className="w-full text-sm border border-gray-200 p-2.5 rounded-lg focus:outline-hidden focus:ring-2 focus:ring-indigo-100 focus:border-indigo-500 bg-white"
                    >
                      <option value={2}>{t('intakeForm.demographics.membersOption', { count: 2 })}</option>
                      <option value={3}>{t('intakeForm.demographics.membersOption', { count: 3 })}</option>
                      <option value={4}>{t('intakeForm.demographics.membersOption', { count: 4 })}</option>
                      <option value={5}>{t('intakeForm.demographics.membersOption', { count: 5 })}</option>
                      <option value={6}>{t('intakeForm.demographics.membersOptionPlus', { count: 6 })}</option>
                    </select>
                  </div>
                </div>
              )}

              {/* Contact phone */}
              <div>
                <label className="block text-xs font-medium text-gray-500 uppercase mb-2">{t('intakeForm.demographics.contactLabel')}</label>
                <input
                  id="field_contactNumber"
                  type="tel"
                  required
                  pattern="[0-9]{10}"
                  value={contactNumber}
                  onChange={(e) => setContactNumber(e.target.value)}
                  placeholder={t('intakeForm.demographics.contactPlaceholder')}
                  className={`w-full text-sm border p-2.5 rounded-lg focus:outline-hidden focus:ring-2 focus:ring-indigo-100 focus:border-indigo-500 ${fieldErrors.contactNumber ? 'border-rose-400 ring-1 ring-rose-200' : 'border-gray-200'}`}
                />
                {fieldErrors.contactNumber && <p className="text-[10px] text-rose-600 mt-1">{fieldErrors.contactNumber}</p>}
              </div>

              {/* Gender and Age — only meaningful for a single Individual; Group members each have their own in the member details section below */}
              {benType === 'Individual' && (
                <>
                  <div>
                    <label className="block text-xs font-medium text-gray-500 uppercase mb-2">{t('intakeForm.demographics.genderLabel')}</label>
                    <select
                      value={gender}
                      onChange={(e) => setGender(e.target.value as any)}
                      className="w-full text-sm border border-gray-200 p-2.5 rounded-lg focus:outline-hidden focus:ring-2 focus:ring-indigo-100 focus:border-indigo-500 bg-white"
                    >
                      <option value="Male">{t('intakeForm.demographics.genderMale')}</option>
                      <option value="Female">{t('intakeForm.demographics.genderFemale')}</option>
                      <option value="Other">{t('intakeForm.demographics.genderOther')}</option>
                      <option value="N/A">{t('intakeForm.demographics.genderNA')}</option>
                    </select>
                  </div>

                  <div>
                    <label className="block text-xs font-medium text-gray-500 uppercase mb-2">{t('intakeForm.demographics.ageLabel')}</label>
                    <input
                      type="number"
                      min={18}
                      max={90}
                      value={age}
                      onChange={(e) => setAge(Number(e.target.value))}
                      className="w-full text-sm border border-gray-200 p-2.5 rounded-lg focus:outline-hidden focus:ring-2 focus:ring-indigo-100 focus:border-indigo-500"
                    />
                  </div>
                </>
              )}

              {/* State and District */}
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-medium text-gray-500 uppercase mb-2">{t('intakeForm.demographics.districtLabel')}</label>
                  <input
                    type="text"
                    value={district}
                    onChange={(e) => setDistrict(e.target.value)}
                    placeholder={t('intakeForm.demographics.districtPlaceholder')}
                    className="w-full text-sm border border-gray-200 p-2.5 rounded-lg focus:outline-hidden focus:ring-2 focus:ring-indigo-100 focus:border-indigo-500"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-500 uppercase mb-2">{t('intakeForm.demographics.stateLabel')}</label>
                  <select
                    value={state}
                    onChange={(e) => setState(e.target.value)}
                    className="w-full text-sm border border-gray-200 p-2.5 rounded-lg bg-white focus:outline-hidden focus:ring-2 focus:ring-indigo-100 focus:border-indigo-500"
                  >
                    {INDIAN_STATES_AND_UTS.map(s => <option key={s} value={s}>{s}</option>)}
                  </select>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3 md:col-span-3">
                <div>
                  <label className="block text-xs font-medium text-gray-500 uppercase mb-2">{t('intakeForm.demographics.projectNameLabel')}</label>
                  <input
                    id="field_projectName"
                    type="text"
                    required
                    value={projectName}
                    onChange={(e) => setProjectName(e.target.value)}
                    placeholder={t('intakeForm.demographics.projectNamePlaceholder')}
                    className={`w-full text-sm border p-2.5 rounded-lg focus:outline-hidden focus:ring-2 focus:ring-indigo-100 focus:border-indigo-500 ${fieldErrors.projectName ? 'border-rose-400 ring-1 ring-rose-200' : 'border-gray-200'}`}
                  />
                  {fieldErrors.projectName && <p className="text-[10px] text-rose-600 mt-1">{fieldErrors.projectName}</p>}
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-500 uppercase mb-2">{t('intakeForm.demographics.fundingPartnerLabel')}</label>
                  <input
                    type="text"
                    value={fundingPartner}
                    onChange={(e) => setFundingPartner(e.target.value)}
                    placeholder={t('intakeForm.demographics.fundingPartnerPlaceholder')}
                    className="w-full text-sm border border-gray-200 p-2.5 rounded-lg focus:outline-hidden focus:ring-2 focus:ring-indigo-100 focus:border-indigo-500"
                  />
                </div>
              </div>

              <div className="md:col-span-3">
                <label className="block text-xs font-medium text-gray-500 uppercase mb-2">{t('intakeForm.demographics.addressLabel')}</label>
                <textarea
                  id="field_address"
                  required
                  rows={2}
                  value={address}
                  onChange={(e) => setAddress(e.target.value)}
                  placeholder={t('intakeForm.demographics.addressPlaceholder')}
                  className={`w-full text-sm border p-2.5 rounded-lg focus:outline-hidden focus:ring-2 focus:ring-indigo-100 focus:border-indigo-500 ${fieldErrors.address ? 'border-rose-400 ring-1 ring-rose-200' : 'border-gray-200'}`}
                />
                {fieldErrors.address && <p className="text-[10px] text-rose-600 mt-1">{fieldErrors.address}</p>}
              </div>

              {benType === 'Group' && (
                <div className="md:col-span-3 space-y-2.5">
                  <label className="block text-xs font-medium text-gray-500 uppercase">
                    {t('intakeForm.demographics.memberDetailsHeading')}
                  </label>
                  {groupMembers.map((member, idx) => (
                    <div key={idx} className="bg-slate-50 border border-gray-150 rounded-lg p-3">
                      <div className="flex items-center justify-between mb-2">
                        <span className="block text-[10px] font-bold text-gray-500 uppercase">
                          {t('intakeForm.demographics.memberLabel', { index: idx + 1 })}
                        </span>
                        {groupMembersCount >= 6 && groupMembers.length > groupMembersCount && (
                          <button
                            type="button"
                            onClick={() => removeGroupMember(idx)}
                            className="text-[10px] font-semibold text-rose-600 hover:text-rose-800 cursor-pointer"
                          >
                            {t('intakeForm.demographics.removeMemberButton')}
                          </button>
                        )}
                      </div>
                      <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                        <div>
                          <input
                            id={`field_member_${idx}_name`}
                            type="text"
                            required
                            value={member.name}
                            onChange={(e) => updateGroupMember(idx, 'name', e.target.value)}
                            placeholder={t('intakeForm.demographics.memberNamePlaceholder')}
                            className={`w-full text-sm border p-2 rounded-lg focus:outline-hidden focus:ring-2 focus:ring-indigo-100 focus:border-indigo-500 ${fieldErrors[`member_${idx}_name`] ? 'border-rose-400 ring-1 ring-rose-200' : 'border-gray-200'}`}
                          />
                          {fieldErrors[`member_${idx}_name`] && <p className="text-[10px] text-rose-600 mt-1">{fieldErrors[`member_${idx}_name`]}</p>}
                        </div>
                        <div>
                          <input
                            id={`field_member_${idx}_age`}
                            type="number"
                            required
                            min={1}
                            max={110}
                            value={member.age}
                            onChange={(e) => updateGroupMember(idx, 'age', Number(e.target.value))}
                            placeholder={t('intakeForm.demographics.ageLabel')}
                            className={`w-full text-sm border p-2 rounded-lg focus:outline-hidden focus:ring-2 focus:ring-indigo-100 focus:border-indigo-500 ${fieldErrors[`member_${idx}_age`] ? 'border-rose-400 ring-1 ring-rose-200' : 'border-gray-200'}`}
                          />
                          {fieldErrors[`member_${idx}_age`] && <p className="text-[10px] text-rose-600 mt-1">{fieldErrors[`member_${idx}_age`]}</p>}
                        </div>
                        <select
                          value={member.gender}
                          onChange={(e) => updateGroupMember(idx, 'gender', e.target.value as GroupMemberDetail['gender'])}
                          className="text-sm border border-gray-200 p-2 rounded-lg bg-white focus:outline-hidden focus:ring-2 focus:ring-indigo-100 focus:border-indigo-500 h-fit"
                        >
                          <option value="Male">{t('intakeForm.demographics.genderMale')}</option>
                          <option value="Female">{t('intakeForm.demographics.genderFemale')}</option>
                          <option value="Other">{t('intakeForm.demographics.genderOther')}</option>
                          <option value="N/A">{t('intakeForm.demographics.genderNA')}</option>
                        </select>
                        <div>
                          <input
                            id={`field_member_${idx}_contact`}
                            type="tel"
                            required
                            pattern="[0-9]{10}"
                            value={member.contactNumber}
                            onChange={(e) => updateGroupMember(idx, 'contactNumber', e.target.value)}
                            placeholder={t('intakeForm.demographics.memberMobilePlaceholder')}
                            className={`w-full text-sm border p-2 rounded-lg focus:outline-hidden focus:ring-2 focus:ring-indigo-100 focus:border-indigo-500 ${fieldErrors[`member_${idx}_contact`] ? 'border-rose-400 ring-1 ring-rose-200' : 'border-gray-200'}`}
                          />
                          {fieldErrors[`member_${idx}_contact`] && <p className="text-[10px] text-rose-600 mt-1">{fieldErrors[`member_${idx}_contact`]}</p>}
                        </div>
                      </div>
                    </div>
                  ))}
                  {groupMembersCount >= 6 && (
                    <button
                      type="button"
                      onClick={addGroupMember}
                      className="flex items-center gap-1.5 text-xs font-semibold text-[#115e59] hover:text-indigo-800 cursor-pointer"
                    >
                      <Plus size={14} />
                      {t('intakeForm.demographics.addMemberButton')}
                    </button>
                  )}
                </div>
              )}
            </div>
            </div>
          </section>

          {/* Section 2: Health details */}
          <section className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
            <div className="bg-gradient-to-r from-rose-700 to-rose-800 px-5 py-3 flex items-center gap-3 border-l-4 border-rose-300">
              <div className="w-9 h-9 rounded-lg bg-white/10 border border-white/20 flex items-center justify-center backdrop-blur-sm shrink-0">
                <HeartPulse className="w-4 h-4 text-rose-100" />
              </div>
              <div className="flex-1 min-w-0">
                <div className="text-[11px] font-bold uppercase tracking-widest text-rose-200">{t('intakeForm.health.stepLabel')}</div>
                <h3 className="text-sm font-bold text-white tracking-tight">{t('intakeForm.health.title')}</h3>
              </div>
              <span className="hidden sm:flex items-center gap-1 text-[11px] uppercase tracking-wider text-white/70 font-semibold">
                <span className="w-1.5 h-1.5 rounded-full bg-rose-300" /> {t('intakeForm.health.clinicalBadge')}
              </span>
            </div>
            <div className="p-5">
              {benType === 'Individual' ? (
              <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
              <div>
                <label className="block text-xs font-medium text-gray-500 uppercase mb-2">{t('intakeForm.health.diseaseCategoryLabel')}</label>
                <div className="grid grid-cols-3 gap-2">
                  <button
                    type="button"
                    onClick={() => setDiseaseType('Leprosy')}
                    className={`py-2 px-2 text-xs font-semibold rounded-lg border text-center transition-all cursor-pointer ${
                      diseaseType === 'Leprosy'
                        ? 'bg-rose-50 border-rose-300 text-rose-800'
                        : 'bg-white border-gray-200 text-gray-700 hover:bg-gray-50'
                    }`}
                  >
                    {t('intakeForm.health.diseaseLeprosy')}
                  </button>
                  <button
                    type="button"
                    onClick={() => setDiseaseType('LF')}
                    className={`py-2 px-2 text-xs font-semibold rounded-lg border text-center transition-all cursor-pointer ${
                      diseaseType === 'LF'
                        ? 'bg-teal-50 border-teal-300 text-teal-800'
                        : 'bg-white border-gray-200 text-gray-700 hover:bg-gray-50'
                    }`}
                  >
                    {t('intakeForm.health.diseaseLF')}
                  </button>
                  <button
                    type="button"
                    onClick={() => setDiseaseType('HIV/AIDS')}
                    className={`py-2 px-2 text-xs font-semibold rounded-lg border text-center transition-all cursor-pointer ${
                      diseaseType === 'HIV/AIDS'
                        ? 'bg-violet-50 border-violet-300 text-violet-800'
                        : 'bg-white border-gray-200 text-gray-700 hover:bg-gray-50'
                    }`}
                  >
                    {t('intakeForm.health.diseaseHiv')}
                  </button>
                </div>
              </div>

              <div>
                <label className="block text-xs font-medium text-gray-500 uppercase mb-2">{t('intakeForm.health.yearDiagnosedLabel')}</label>
                <input
                  type="number"
                  min={2000}
                  max={2026}
                  value={diagnosisYear}
                  onChange={(e) => setDiagnosisYear(Number(e.target.value))}
                  className="w-full text-sm border border-gray-200 p-2.5 rounded-lg focus:outline-hidden focus:ring-2 focus:ring-indigo-100 focus:border-indigo-500"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-gray-500 uppercase mb-2">{t('intakeForm.health.treatmentStatusLabel')}</label>
                <select
                  value={treatmentStatus}
                  onChange={(e) => setTreatmentStatus(e.target.value as TreatmentStatus)}
                  className="w-full text-sm border border-gray-200 p-2.5 rounded-lg focus:outline-hidden focus:ring-2 focus:ring-indigo-100 focus:border-indigo-500 bg-white"
                >
                  <option value="Completed">{t('intakeForm.health.treatmentCompleted')}</option>
                  <option value="Under Treatment">{t('intakeForm.health.treatmentUnder')}</option>
                  <option value="Rehabilitation">{t('intakeForm.health.treatmentRehabilitation')}</option>
                </select>
              </div>

              {/* Physical Impairments Checkboxes */}
              <div className="md:col-span-3">
                <label className="block text-xs font-medium text-gray-500 uppercase mb-2">{t('intakeForm.health.impairmentsLabel')}</label>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                  {IMPAIRMENT_OPTIONS.map(({ value: lim, labelKey }) => (
                    <button
                      type="button"
                      key={lim}
                      onClick={() => handleLimitationToggle(lim)}
                      className={`p-2.5 text-xs font-medium rounded-lg border text-left flex items-center justify-between transition-colors cursor-pointer ${
                        limitations.includes(lim)
                          ? 'bg-sky-50 border-sky-300 text-sky-800'
                          : 'bg-white border-gray-200 text-gray-600 hover:bg-gray-50'
                      }`}
                    >
                      <span>{t(`intakeForm.health.impairments.${labelKey}`)}</span>
                      {limitations.includes(lim) && <Check className="w-3.5 h-3.5 text-sky-600 shrink-0" />}
                    </button>
                  ))}
                </div>
              </div>

              {/* LF (Lymphatic Filariasis) specific impairment / limitation indicators */}
              {diseaseType === 'LF' && (
                <div className="md:col-span-3">
                  <div className="bg-teal-50/60 border border-teal-200 rounded-lg p-4 space-y-4 animate-fade-in">
                    <div className="flex items-center gap-2">
                      <Activity className="w-4 h-4 text-teal-700" />
                      <span className="text-[11px] font-bold text-teal-800 uppercase tracking-wider">{t('intakeForm.health.lf.sectionTitle')}</span>
                    </div>
                    <p className="text-[10px] text-teal-700/80 leading-normal">
                      {t('intakeForm.health.lf.sectionDescription')}
                    </p>

                    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                      {/* Grade of Disease */}
                      <div>
                        <label className="block text-xs font-medium text-gray-500 uppercase mb-2">{t('intakeForm.health.lf.gradeLabel')}</label>
                        <select
                          value={lfGrade}
                          onChange={(e) => setLfGrade(e.target.value as LFDiseaseGrade)}
                          className="w-full text-sm border border-gray-200 p-2.5 rounded-lg focus:outline-hidden focus:ring-2 focus:ring-teal-100 focus:border-teal-500 bg-white"
                        >
                          <option value="Not Assessed">{t('intakeForm.health.lf.gradeNotAssessed')}</option>
                          <option value="Grade 1">{t('intakeForm.health.lf.grade1')}</option>
                          <option value="Grade 2">{t('intakeForm.health.lf.grade2')}</option>
                          <option value="Grade 3">{t('intakeForm.health.lf.grade3')}</option>
                          <option value="Grade 4">{t('intakeForm.health.lf.grade4')}</option>
                        </select>
                      </div>

                      {/* Reduced mobility / immobility status */}
                      <div>
                        <label className="block text-xs font-medium text-gray-500 uppercase mb-2">{t('intakeForm.health.lf.mobilityLabel')}</label>
                        <select
                          value={lfMobility}
                          onChange={(e) => setLfMobility(e.target.value as LFMobilityStatus)}
                          className="w-full text-sm border border-gray-200 p-2.5 rounded-lg focus:outline-hidden focus:ring-2 focus:ring-teal-100 focus:border-teal-500 bg-white"
                        >
                          <option value="Normal Mobility">{t('intakeForm.health.lf.mobilityNormal')}</option>
                          <option value="Reduced Mobility">{t('intakeForm.health.lf.mobilityReduced')}</option>
                          <option value="Immobile">{t('intakeForm.health.lf.mobilityImmobile')}</option>
                        </select>
                      </div>

                      {/* Frequency of acute attacks */}
                      <div>
                        <label className="block text-xs font-medium text-gray-500 uppercase mb-2">{t('intakeForm.health.lf.attacksLabel')}</label>
                        <select
                          value={lfAttacks}
                          onChange={(e) => setLfAttacks(e.target.value as LFAttackFrequency)}
                          className="w-full text-sm border border-gray-200 p-2.5 rounded-lg focus:outline-hidden focus:ring-2 focus:ring-teal-100 focus:border-teal-500 bg-white"
                        >
                          <option value="None">{t('intakeForm.health.lf.attacksNone')}</option>
                          <option value="Rare (1-2 / year)">{t('intakeForm.health.lf.attacksRare')}</option>
                          <option value="Occasional (3-5 / year)">{t('intakeForm.health.lf.attacksOccasional')}</option>
                          <option value="Frequent (&gt; 5 / year)">{t('intakeForm.health.lf.attacksFrequent')}</option>
                        </select>
                      </div>
                    </div>

                    {/* Presence of entry lesions */}
                    <div>
                      <label className="block text-xs font-medium text-gray-500 uppercase mb-2">{t('intakeForm.health.lf.entryLesionsLabel')}</label>
                      <div className="grid grid-cols-2 gap-2 max-w-xs">
                        <button
                          type="button"
                          onClick={() => setLfEntryLesions(true)}
                          className={`py-2 px-3 text-xs font-semibold rounded-lg border text-center transition-all cursor-pointer ${
                            lfEntryLesions
                              ? 'bg-rose-50 border-rose-300 text-rose-800'
                              : 'bg-white border-gray-200 text-gray-700 hover:bg-gray-50'
                          }`}
                        >
                          {t('intakeForm.health.lf.entryLesionsPresent')}
                        </button>
                        <button
                          type="button"
                          onClick={() => setLfEntryLesions(false)}
                          className={`py-2 px-3 text-xs font-semibold rounded-lg border text-center transition-all cursor-pointer ${
                            !lfEntryLesions
                              ? 'bg-emerald-50 border-emerald-300 text-emerald-800'
                              : 'bg-white border-gray-200 text-gray-700 hover:bg-gray-50'
                          }`}
                        >
                          {t('intakeForm.health.lf.entryLesionsAbsent')}
                        </button>
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {/* HIV/AIDS & High-Risk Group (HRG) vulnerability indicators */}
              {diseaseType === 'HIV/AIDS' && (
                <div className="md:col-span-3">
                  <div className="bg-violet-50/60 border border-violet-200 rounded-lg p-4 space-y-5 animate-fade-in">
                    <div className="flex items-center gap-2">
                      <ShieldAlert className="w-4 h-4 text-violet-700" />
                      <span className="text-[11px] font-bold text-violet-800 uppercase tracking-wider">{t('intakeForm.health.hiv.sectionTitle')}</span>
                    </div>
                    <p className="text-[10px] text-violet-700/80 leading-normal">
                      {t('intakeForm.health.hiv.sectionDescription')}
                    </p>

                    {/* A. High-Risk Group Status */}
                    <div className="space-y-2">
                      <span className="text-[10px] font-bold text-violet-900 uppercase tracking-wider block">{t('intakeForm.health.hiv.hrgSectionTitle')}</span>
                      <div>
                        <label className="block text-xs font-medium text-gray-500 uppercase mb-2">{t('intakeForm.health.hiv.hrgMemberLabel')}</label>
                        <div className="grid grid-cols-2 gap-2 max-w-xs">
                          <button
                            type="button"
                            onClick={() => setHivIsHrgMember(true)}
                            className={`py-2 px-3 text-xs font-semibold rounded-lg border text-center transition-all cursor-pointer ${
                              hivIsHrgMember
                                ? 'bg-violet-100 border-violet-300 text-violet-800'
                                : 'bg-white border-gray-200 text-gray-700 hover:bg-gray-50'
                            }`}
                          >
                            {t('intakeForm.health.hiv.yes')}
                          </button>
                          <button
                            type="button"
                            onClick={() => setHivIsHrgMember(false)}
                            className={`py-2 px-3 text-xs font-semibold rounded-lg border text-center transition-all cursor-pointer ${
                              !hivIsHrgMember
                                ? 'bg-emerald-50 border-emerald-300 text-emerald-800'
                                : 'bg-white border-gray-200 text-gray-700 hover:bg-gray-50'
                            }`}
                          >
                            {t('intakeForm.health.hiv.no')}
                          </button>
                        </div>
                      </div>

                      {hivIsHrgMember && (
                        <div className="max-w-sm">
                          <label className="block text-xs font-medium text-gray-500 uppercase mb-2">{t('intakeForm.health.hiv.hrgTypeLabel')}</label>
                          <select
                            value={hivHrgType}
                            onChange={(e) => setHivHrgType(e.target.value as HrgType)}
                            className="w-full text-sm border border-gray-200 p-2.5 rounded-lg focus:outline-hidden focus:ring-2 focus:ring-violet-100 focus:border-violet-500 bg-white"
                          >
                            <option value="FSW">{t('intakeForm.health.hiv.hrgTypeFsw')}</option>
                            <option value="MSM">{t('intakeForm.health.hiv.hrgTypeMsm')}</option>
                            <option value="IDU">{t('intakeForm.health.hiv.hrgTypeIdu')}</option>
                          </select>
                        </div>
                      )}
                    </div>

                    {/* B. HIV Status */}
                    <div className="space-y-2 pt-1 border-t border-violet-100">
                      <span className="text-[10px] font-bold text-violet-900 uppercase tracking-wider block pt-3">{t('intakeForm.health.hiv.hivStatusSectionTitle')}</span>
                      <div>
                        <label className="block text-xs font-medium text-gray-500 uppercase mb-2">{t('intakeForm.health.hiv.livingWithHivLabel')}</label>
                        <div className="grid grid-cols-2 gap-2 max-w-xs">
                          <button
                            type="button"
                            onClick={() => setHivIsLivingWithHiv(true)}
                            className={`py-2 px-3 text-xs font-semibold rounded-lg border text-center transition-all cursor-pointer ${
                              hivIsLivingWithHiv
                                ? 'bg-violet-100 border-violet-300 text-violet-800'
                                : 'bg-white border-gray-200 text-gray-700 hover:bg-gray-50'
                            }`}
                          >
                            {t('intakeForm.health.hiv.yes')}
                          </button>
                          <button
                            type="button"
                            onClick={() => setHivIsLivingWithHiv(false)}
                            className={`py-2 px-3 text-xs font-semibold rounded-lg border text-center transition-all cursor-pointer ${
                              !hivIsLivingWithHiv
                                ? 'bg-emerald-50 border-emerald-300 text-emerald-800'
                                : 'bg-white border-gray-200 text-gray-700 hover:bg-gray-50'
                            }`}
                          >
                            {t('intakeForm.health.hiv.no')}
                          </button>
                        </div>
                      </div>

                      {hivIsLivingWithHiv && (
                        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                          <div>
                            <label className="block text-xs font-medium text-gray-500 uppercase mb-2">{t('intakeForm.health.hiv.yearOfDiagnosisLabel')}</label>
                            <input
                              type="number"
                              min={1990}
                              max={2026}
                              value={hivYearOfDiagnosis}
                              onChange={(e) => setHivYearOfDiagnosis(Number(e.target.value))}
                              className="w-full text-sm border border-gray-200 p-2.5 rounded-lg focus:outline-hidden focus:ring-2 focus:ring-violet-100 focus:border-violet-500 bg-white"
                            />
                          </div>
                          <div>
                            <label className="block text-xs font-medium text-gray-500 uppercase mb-2">{t('intakeForm.health.hiv.onArtLabel')}</label>
                            <div className="grid grid-cols-2 gap-2">
                              <button
                                type="button"
                                onClick={() => setHivOnArt(true)}
                                className={`py-2 px-2 text-xs font-semibold rounded-lg border text-center transition-all cursor-pointer ${
                                  hivOnArt
                                    ? 'bg-violet-100 border-violet-300 text-violet-800'
                                    : 'bg-white border-gray-200 text-gray-700 hover:bg-gray-50'
                                }`}
                              >
                                {t('intakeForm.health.hiv.yes')}
                              </button>
                              <button
                                type="button"
                                onClick={() => setHivOnArt(false)}
                                className={`py-2 px-2 text-xs font-semibold rounded-lg border text-center transition-all cursor-pointer ${
                                  !hivOnArt
                                    ? 'bg-emerald-50 border-emerald-300 text-emerald-800'
                                    : 'bg-white border-gray-200 text-gray-700 hover:bg-gray-50'
                                }`}
                              >
                                {t('intakeForm.health.hiv.no')}
                              </button>
                            </div>
                          </div>
                          {hivOnArt && (
                            <div>
                              <label className="block text-xs font-medium text-gray-500 uppercase mb-2">{t('intakeForm.health.hiv.artDurationLabel')}</label>
                              <input
                                type="text"
                                value={hivArtDuration}
                                onChange={(e) => setHivArtDuration(e.target.value)}
                                placeholder={t('intakeForm.health.hiv.artDurationPlaceholder')}
                                className="w-full text-sm border border-gray-200 p-2.5 rounded-lg focus:outline-hidden focus:ring-2 focus:ring-violet-100 focus:border-violet-500"
                              />
                            </div>
                          )}
                        </div>
                      )}
                    </div>

                    {/* C. Safe Sex Practice */}
                    <div className="pt-1 border-t border-violet-100">
                      <label className="block text-xs font-medium text-gray-500 uppercase mb-2 pt-3">{t('intakeForm.health.hiv.safeSexLabel')}</label>
                      <div className="grid grid-cols-2 gap-2 max-w-xs">
                        <button
                          type="button"
                          onClick={() => setHivPractisesSafeSex(true)}
                          className={`py-2 px-3 text-xs font-semibold rounded-lg border text-center transition-all cursor-pointer ${
                            hivPractisesSafeSex
                              ? 'bg-emerald-50 border-emerald-300 text-emerald-800'
                              : 'bg-white border-gray-200 text-gray-700 hover:bg-gray-50'
                          }`}
                        >
                          {t('intakeForm.health.hiv.yes')}
                        </button>
                        <button
                          type="button"
                          onClick={() => setHivPractisesSafeSex(false)}
                          className={`py-2 px-3 text-xs font-semibold rounded-lg border text-center transition-all cursor-pointer ${
                            !hivPractisesSafeSex
                              ? 'bg-rose-50 border-rose-300 text-rose-800'
                              : 'bg-white border-gray-200 text-gray-700 hover:bg-gray-50'
                          }`}
                        >
                          {t('intakeForm.health.hiv.no')}
                        </button>
                      </div>
                    </div>
                  </div>
                </div>
              )}
              </div>
              ) : (
                <div className="space-y-3">
                  <p className="text-[11px] text-gray-500 leading-normal">{t('intakeForm.health.groupNotice')}</p>
                  {groupMembers.map((member, idx) => (
                    <div key={idx} className="bg-slate-50 border border-gray-150 rounded-lg p-3 space-y-4">
                      <span className="block text-[10px] font-bold text-gray-500 uppercase">
                        {t('intakeForm.demographics.memberLabel', { index: idx + 1 })}{member.name ? ` — ${member.name}` : ''}
                      </span>
                      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                        <div>
                          <label className="block text-xs font-medium text-gray-500 uppercase mb-2">{t('intakeForm.health.diseaseCategoryLabel')}</label>
                          <div className="grid grid-cols-3 gap-2">
                            <button
                              type="button"
                              onClick={() => updateGroupMember(idx, 'diseaseType', 'Leprosy')}
                              className={`py-2 px-2 text-xs font-semibold rounded-lg border text-center transition-all cursor-pointer ${
                                member.diseaseType === 'Leprosy'
                                  ? 'bg-rose-50 border-rose-300 text-rose-800'
                                  : 'bg-white border-gray-200 text-gray-700 hover:bg-gray-50'
                              }`}
                            >
                              {t('intakeForm.health.diseaseLeprosy')}
                            </button>
                            <button
                              type="button"
                              onClick={() => updateGroupMember(idx, 'diseaseType', 'LF')}
                              className={`py-2 px-2 text-xs font-semibold rounded-lg border text-center transition-all cursor-pointer ${
                                member.diseaseType === 'LF'
                                  ? 'bg-teal-50 border-teal-300 text-teal-800'
                                  : 'bg-white border-gray-200 text-gray-700 hover:bg-gray-50'
                              }`}
                            >
                              {t('intakeForm.health.diseaseLF')}
                            </button>
                            <button
                              type="button"
                              onClick={() => updateGroupMember(idx, 'diseaseType', 'HIV/AIDS')}
                              className={`py-2 px-2 text-xs font-semibold rounded-lg border text-center transition-all cursor-pointer ${
                                member.diseaseType === 'HIV/AIDS'
                                  ? 'bg-violet-50 border-violet-300 text-violet-800'
                                  : 'bg-white border-gray-200 text-gray-700 hover:bg-gray-50'
                              }`}
                            >
                              {t('intakeForm.health.diseaseHiv')}
                            </button>
                          </div>
                        </div>

                        <div>
                          <label className="block text-xs font-medium text-gray-500 uppercase mb-2">{t('intakeForm.health.yearDiagnosedLabel')}</label>
                          <input
                            type="number"
                            min={2000}
                            max={2026}
                            value={member.diagnosisYear}
                            onChange={(e) => updateGroupMember(idx, 'diagnosisYear', Number(e.target.value))}
                            className="w-full text-sm border border-gray-200 p-2.5 rounded-lg focus:outline-hidden focus:ring-2 focus:ring-indigo-100 focus:border-indigo-500 bg-white"
                          />
                        </div>

                        <div>
                          <label className="block text-xs font-medium text-gray-500 uppercase mb-2">{t('intakeForm.health.treatmentStatusLabel')}</label>
                          <select
                            value={member.treatmentStatus}
                            onChange={(e) => updateGroupMember(idx, 'treatmentStatus', e.target.value as TreatmentStatus)}
                            className="w-full text-sm border border-gray-200 p-2.5 rounded-lg focus:outline-hidden focus:ring-2 focus:ring-indigo-100 focus:border-indigo-500 bg-white"
                          >
                            <option value="Completed">{t('intakeForm.health.treatmentCompleted')}</option>
                            <option value="Under Treatment">{t('intakeForm.health.treatmentUnder')}</option>
                            <option value="Rehabilitation">{t('intakeForm.health.treatmentRehabilitation')}</option>
                          </select>
                        </div>

                        {/* Physical Impairments Checkboxes */}
                        <div className="md:col-span-3">
                          <label className="block text-xs font-medium text-gray-500 uppercase mb-2">{t('intakeForm.health.impairmentsLabel')}</label>
                          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                            {IMPAIRMENT_OPTIONS.map(({ value: lim, labelKey }) => (
                              <button
                                type="button"
                                key={lim}
                                onClick={() => updateGroupMemberLimitationToggle(idx, lim)}
                                className={`p-2.5 text-xs font-medium rounded-lg border text-left flex items-center justify-between transition-colors cursor-pointer ${
                                  member.physicalLimitations.includes(lim)
                                    ? 'bg-sky-50 border-sky-300 text-sky-800'
                                    : 'bg-white border-gray-200 text-gray-600 hover:bg-gray-50'
                                }`}
                              >
                                <span>{t(`intakeForm.health.impairments.${labelKey}`)}</span>
                                {member.physicalLimitations.includes(lim) && <Check className="w-3.5 h-3.5 text-sky-600 shrink-0" />}
                              </button>
                            ))}
                          </div>
                        </div>

                        {/* LF (Lymphatic Filariasis) specific impairment / limitation indicators */}
                        {member.diseaseType === 'LF' && (
                          <div className="md:col-span-3">
                            <div className="bg-teal-50/60 border border-teal-200 rounded-lg p-4 space-y-4 animate-fade-in">
                              <div className="flex items-center gap-2">
                                <Activity className="w-4 h-4 text-teal-700" />
                                <span className="text-[11px] font-bold text-teal-800 uppercase tracking-wider">{t('intakeForm.health.lf.sectionTitle')}</span>
                              </div>

                              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                                <div>
                                  <label className="block text-xs font-medium text-gray-500 uppercase mb-2">{t('intakeForm.health.lf.gradeLabel')}</label>
                                  <select
                                    value={member.lfIndicators?.diseaseGrade ?? 'Not Assessed'}
                                    onChange={(e) => updateGroupMemberLf(idx, 'diseaseGrade', e.target.value as LFDiseaseGrade)}
                                    className="w-full text-sm border border-gray-200 p-2.5 rounded-lg focus:outline-hidden focus:ring-2 focus:ring-teal-100 focus:border-teal-500 bg-white"
                                  >
                                    <option value="Not Assessed">{t('intakeForm.health.lf.gradeNotAssessed')}</option>
                                    <option value="Grade 1">{t('intakeForm.health.lf.grade1')}</option>
                                    <option value="Grade 2">{t('intakeForm.health.lf.grade2')}</option>
                                    <option value="Grade 3">{t('intakeForm.health.lf.grade3')}</option>
                                    <option value="Grade 4">{t('intakeForm.health.lf.grade4')}</option>
                                  </select>
                                </div>

                                <div>
                                  <label className="block text-xs font-medium text-gray-500 uppercase mb-2">{t('intakeForm.health.lf.mobilityLabel')}</label>
                                  <select
                                    value={member.lfIndicators?.mobilityStatus ?? 'Normal Mobility'}
                                    onChange={(e) => updateGroupMemberLf(idx, 'mobilityStatus', e.target.value as LFMobilityStatus)}
                                    className="w-full text-sm border border-gray-200 p-2.5 rounded-lg focus:outline-hidden focus:ring-2 focus:ring-teal-100 focus:border-teal-500 bg-white"
                                  >
                                    <option value="Normal Mobility">{t('intakeForm.health.lf.mobilityNormal')}</option>
                                    <option value="Reduced Mobility">{t('intakeForm.health.lf.mobilityReduced')}</option>
                                    <option value="Immobile">{t('intakeForm.health.lf.mobilityImmobile')}</option>
                                  </select>
                                </div>

                                <div>
                                  <label className="block text-xs font-medium text-gray-500 uppercase mb-2">{t('intakeForm.health.lf.attacksLabel')}</label>
                                  <select
                                    value={member.lfIndicators?.acuteAttackFrequency ?? 'None'}
                                    onChange={(e) => updateGroupMemberLf(idx, 'acuteAttackFrequency', e.target.value as LFAttackFrequency)}
                                    className="w-full text-sm border border-gray-200 p-2.5 rounded-lg focus:outline-hidden focus:ring-2 focus:ring-teal-100 focus:border-teal-500 bg-white"
                                  >
                                    <option value="None">{t('intakeForm.health.lf.attacksNone')}</option>
                                    <option value="Rare (1-2 / year)">{t('intakeForm.health.lf.attacksRare')}</option>
                                    <option value="Occasional (3-5 / year)">{t('intakeForm.health.lf.attacksOccasional')}</option>
                                    <option value="Frequent (&gt; 5 / year)">{t('intakeForm.health.lf.attacksFrequent')}</option>
                                  </select>
                                </div>
                              </div>

                              <div>
                                <label className="block text-xs font-medium text-gray-500 uppercase mb-2">{t('intakeForm.health.lf.entryLesionsLabel')}</label>
                                <div className="grid grid-cols-2 gap-2 max-w-xs">
                                  <button
                                    type="button"
                                    onClick={() => updateGroupMemberLf(idx, 'entryLesionsPresent', true)}
                                    className={`py-2 px-3 text-xs font-semibold rounded-lg border text-center transition-all cursor-pointer ${
                                      member.lfIndicators?.entryLesionsPresent
                                        ? 'bg-rose-50 border-rose-300 text-rose-800'
                                        : 'bg-white border-gray-200 text-gray-700 hover:bg-gray-50'
                                    }`}
                                  >
                                    {t('intakeForm.health.lf.entryLesionsPresent')}
                                  </button>
                                  <button
                                    type="button"
                                    onClick={() => updateGroupMemberLf(idx, 'entryLesionsPresent', false)}
                                    className={`py-2 px-3 text-xs font-semibold rounded-lg border text-center transition-all cursor-pointer ${
                                      !member.lfIndicators?.entryLesionsPresent
                                        ? 'bg-emerald-50 border-emerald-300 text-emerald-800'
                                        : 'bg-white border-gray-200 text-gray-700 hover:bg-gray-50'
                                    }`}
                                  >
                                    {t('intakeForm.health.lf.entryLesionsAbsent')}
                                  </button>
                                </div>
                              </div>
                            </div>
                          </div>
                        )}

                        {/* HIV/AIDS & High-Risk Group (HRG) vulnerability indicators */}
                        {member.diseaseType === 'HIV/AIDS' && (
                          <div className="md:col-span-3">
                            <div className="bg-violet-50/60 border border-violet-200 rounded-lg p-4 space-y-5 animate-fade-in">
                              <div className="flex items-center gap-2">
                                <ShieldAlert className="w-4 h-4 text-violet-700" />
                                <span className="text-[11px] font-bold text-violet-800 uppercase tracking-wider">{t('intakeForm.health.hiv.sectionTitle')}</span>
                              </div>

                              {/* A. High-Risk Group Status */}
                              <div className="space-y-2">
                                <span className="text-[10px] font-bold text-violet-900 uppercase tracking-wider block">{t('intakeForm.health.hiv.hrgSectionTitle')}</span>
                                <div>
                                  <label className="block text-xs font-medium text-gray-500 uppercase mb-2">{t('intakeForm.health.hiv.hrgMemberLabel')}</label>
                                  <div className="grid grid-cols-2 gap-2 max-w-xs">
                                    <button
                                      type="button"
                                      onClick={() => updateGroupMemberHiv(idx, 'isHrgMember', true)}
                                      className={`py-2 px-3 text-xs font-semibold rounded-lg border text-center transition-all cursor-pointer ${
                                        member.hivIndicators?.isHrgMember
                                          ? 'bg-violet-100 border-violet-300 text-violet-800'
                                          : 'bg-white border-gray-200 text-gray-700 hover:bg-gray-50'
                                      }`}
                                    >
                                      {t('intakeForm.health.hiv.yes')}
                                    </button>
                                    <button
                                      type="button"
                                      onClick={() => updateGroupMemberHiv(idx, 'isHrgMember', false)}
                                      className={`py-2 px-3 text-xs font-semibold rounded-lg border text-center transition-all cursor-pointer ${
                                        !member.hivIndicators?.isHrgMember
                                          ? 'bg-emerald-50 border-emerald-300 text-emerald-800'
                                          : 'bg-white border-gray-200 text-gray-700 hover:bg-gray-50'
                                      }`}
                                    >
                                      {t('intakeForm.health.hiv.no')}
                                    </button>
                                  </div>
                                </div>

                                {member.hivIndicators?.isHrgMember && (
                                  <div className="max-w-sm">
                                    <label className="block text-xs font-medium text-gray-500 uppercase mb-2">{t('intakeForm.health.hiv.hrgTypeLabel')}</label>
                                    <select
                                      value={member.hivIndicators?.hrgType ?? 'FSW'}
                                      onChange={(e) => updateGroupMemberHiv(idx, 'hrgType', e.target.value as HrgType)}
                                      className="w-full text-sm border border-gray-200 p-2.5 rounded-lg focus:outline-hidden focus:ring-2 focus:ring-violet-100 focus:border-violet-500 bg-white"
                                    >
                                      <option value="FSW">{t('intakeForm.health.hiv.hrgTypeFsw')}</option>
                                      <option value="MSM">{t('intakeForm.health.hiv.hrgTypeMsm')}</option>
                                      <option value="IDU">{t('intakeForm.health.hiv.hrgTypeIdu')}</option>
                                    </select>
                                  </div>
                                )}
                              </div>

                              {/* B. HIV Status */}
                              <div className="space-y-2 pt-1 border-t border-violet-100">
                                <span className="text-[10px] font-bold text-violet-900 uppercase tracking-wider block pt-3">{t('intakeForm.health.hiv.hivStatusSectionTitle')}</span>
                                <div>
                                  <label className="block text-xs font-medium text-gray-500 uppercase mb-2">{t('intakeForm.health.hiv.livingWithHivLabel')}</label>
                                  <div className="grid grid-cols-2 gap-2 max-w-xs">
                                    <button
                                      type="button"
                                      onClick={() => updateGroupMemberHiv(idx, 'isLivingWithHiv', true)}
                                      className={`py-2 px-3 text-xs font-semibold rounded-lg border text-center transition-all cursor-pointer ${
                                        member.hivIndicators?.isLivingWithHiv
                                          ? 'bg-violet-100 border-violet-300 text-violet-800'
                                          : 'bg-white border-gray-200 text-gray-700 hover:bg-gray-50'
                                      }`}
                                    >
                                      {t('intakeForm.health.hiv.yes')}
                                    </button>
                                    <button
                                      type="button"
                                      onClick={() => updateGroupMemberHiv(idx, 'isLivingWithHiv', false)}
                                      className={`py-2 px-3 text-xs font-semibold rounded-lg border text-center transition-all cursor-pointer ${
                                        !member.hivIndicators?.isLivingWithHiv
                                          ? 'bg-emerald-50 border-emerald-300 text-emerald-800'
                                          : 'bg-white border-gray-200 text-gray-700 hover:bg-gray-50'
                                      }`}
                                    >
                                      {t('intakeForm.health.hiv.no')}
                                    </button>
                                  </div>
                                </div>

                                {member.hivIndicators?.isLivingWithHiv && (
                                  <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                                    <div>
                                      <label className="block text-xs font-medium text-gray-500 uppercase mb-2">{t('intakeForm.health.hiv.yearOfDiagnosisLabel')}</label>
                                      <input
                                        type="number"
                                        min={1990}
                                        max={2026}
                                        value={member.hivIndicators?.yearOfDiagnosis ?? 2024}
                                        onChange={(e) => updateGroupMemberHiv(idx, 'yearOfDiagnosis', Number(e.target.value))}
                                        className="w-full text-sm border border-gray-200 p-2.5 rounded-lg focus:outline-hidden focus:ring-2 focus:ring-violet-100 focus:border-violet-500 bg-white"
                                      />
                                    </div>
                                    <div>
                                      <label className="block text-xs font-medium text-gray-500 uppercase mb-2">{t('intakeForm.health.hiv.onArtLabel')}</label>
                                      <div className="grid grid-cols-2 gap-2">
                                        <button
                                          type="button"
                                          onClick={() => updateGroupMemberHiv(idx, 'onArt', true)}
                                          className={`py-2 px-2 text-xs font-semibold rounded-lg border text-center transition-all cursor-pointer ${
                                            member.hivIndicators?.onArt
                                              ? 'bg-violet-100 border-violet-300 text-violet-800'
                                              : 'bg-white border-gray-200 text-gray-700 hover:bg-gray-50'
                                          }`}
                                        >
                                          {t('intakeForm.health.hiv.yes')}
                                        </button>
                                        <button
                                          type="button"
                                          onClick={() => updateGroupMemberHiv(idx, 'onArt', false)}
                                          className={`py-2 px-2 text-xs font-semibold rounded-lg border text-center transition-all cursor-pointer ${
                                            !member.hivIndicators?.onArt
                                              ? 'bg-emerald-50 border-emerald-300 text-emerald-800'
                                              : 'bg-white border-gray-200 text-gray-700 hover:bg-gray-50'
                                          }`}
                                        >
                                          {t('intakeForm.health.hiv.no')}
                                        </button>
                                      </div>
                                    </div>
                                    {member.hivIndicators?.onArt && (
                                      <div>
                                        <label className="block text-xs font-medium text-gray-500 uppercase mb-2">{t('intakeForm.health.hiv.artDurationLabel')}</label>
                                        <input
                                          type="text"
                                          value={member.hivIndicators?.artDuration ?? ''}
                                          onChange={(e) => updateGroupMemberHiv(idx, 'artDuration', e.target.value)}
                                          placeholder={t('intakeForm.health.hiv.artDurationPlaceholder')}
                                          className="w-full text-sm border border-gray-200 p-2.5 rounded-lg focus:outline-hidden focus:ring-2 focus:ring-violet-100 focus:border-violet-500"
                                        />
                                      </div>
                                    )}
                                  </div>
                                )}
                              </div>

                              {/* C. Safe Sex Practice */}
                              <div className="pt-1 border-t border-violet-100">
                                <label className="block text-xs font-medium text-gray-500 uppercase mb-2 pt-3">{t('intakeForm.health.hiv.safeSexLabel')}</label>
                                <div className="grid grid-cols-2 gap-2 max-w-xs">
                                  <button
                                    type="button"
                                    onClick={() => updateGroupMemberHiv(idx, 'practicesSafeSex', true)}
                                    className={`py-2 px-3 text-xs font-semibold rounded-lg border text-center transition-all cursor-pointer ${
                                      member.hivIndicators?.practicesSafeSex
                                        ? 'bg-emerald-50 border-emerald-300 text-emerald-800'
                                        : 'bg-white border-gray-200 text-gray-700 hover:bg-gray-50'
                                    }`}
                                  >
                                    {t('intakeForm.health.hiv.yes')}
                                  </button>
                                  <button
                                    type="button"
                                    onClick={() => updateGroupMemberHiv(idx, 'practicesSafeSex', false)}
                                    className={`py-2 px-3 text-xs font-semibold rounded-lg border text-center transition-all cursor-pointer ${
                                      !member.hivIndicators?.practicesSafeSex
                                        ? 'bg-rose-50 border-rose-300 text-rose-800'
                                        : 'bg-white border-gray-200 text-gray-700 hover:bg-gray-50'
                                    }`}
                                  >
                                    {t('intakeForm.health.hiv.no')}
                                  </button>
                                </div>
                              </div>
                            </div>
                          </div>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </section>

          {/* Section 3: Business Plan */}
          <section className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
            <div className="bg-gradient-to-r from-indigo-700 to-indigo-800 px-5 py-3 flex items-center gap-3 border-l-4 border-indigo-300">
              <div className="w-9 h-9 rounded-lg bg-white/10 border border-white/20 flex items-center justify-center backdrop-blur-sm shrink-0">
                <Briefcase className="w-4 h-4 text-indigo-100" />
              </div>
              <div className="flex-1 min-w-0">
                <div className="text-[11px] font-bold uppercase tracking-widest text-indigo-200">{t('intakeForm.business.stepLabel')}</div>
                <h3 className="text-sm font-bold text-white tracking-tight">{t('intakeForm.business.title')}</h3>
              </div>
              <span className="hidden sm:flex items-center gap-1 text-[11px] uppercase tracking-wider text-white/70 font-semibold">
                <span className="w-1.5 h-1.5 rounded-full bg-indigo-300" /> {t('intakeForm.business.capitalBadge')}
              </span>
            </div>
            <div className="p-5">
              <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
              <div>
                <label className="block text-xs font-medium text-gray-500 uppercase mb-2">{t('intakeForm.business.nameLabel')}</label>
                <input
                  type="text"
                  value={businessName}
                  onChange={(e) => setBusinessName(e.target.value)}
                  placeholder={t('intakeForm.business.namePlaceholder')}
                  className="w-full text-sm border border-gray-200 p-2.5 rounded-lg focus:outline-hidden focus:ring-2 focus:ring-indigo-100 focus:border-indigo-500"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-gray-500 uppercase mb-2">{t('intakeForm.business.sectorLabel')}</label>
                <select
                  value={businessSector}
                  onChange={(e) => setBusinessSector(e.target.value)}
                  className="w-full text-sm border border-gray-200 p-2.5 rounded-lg focus:outline-hidden focus:ring-2 focus:ring-indigo-100 focus:border-indigo-500 bg-white"
                >
                  <option value="Petty Shop">{t('intakeForm.business.sectors.pettyShop')}</option>
                  <option value="Goat Rearing">{t('intakeForm.business.sectors.goatRearing')}</option>
                  <option value="Tailoring">{t('intakeForm.business.sectors.tailoring')}</option>
                  <option value="Tea Stall">{t('intakeForm.business.sectors.teaStall')}</option>
                  <option value="Cycle Repair">{t('intakeForm.business.sectors.cycleRepair')}</option>
                  <option value="Poultry">{t('intakeForm.business.sectors.poultry')}</option>
                  <option value="Fancy Goods">{t('intakeForm.business.sectors.fancyGoods')}</option>
                  <option value="Basket Making">{t('intakeForm.business.sectors.basketMaking')}</option>
                  <option value="Mushroom Cultivation">{t('intakeForm.business.sectors.mushroomCultivation')}</option>
                  <option value="Other">{t('intakeForm.business.sectors.other')}</option>
                </select>
                {businessSector === 'Other' && (
                  <>
                  <input
                    id="field_businessSectorOther"
                    type="text"
                    required
                    value={businessSectorOther}
                    onChange={(e) => setBusinessSectorOther(e.target.value)}
                    placeholder={t('intakeForm.business.sectorOtherPlaceholder')}
                    className={`w-full text-sm border p-2.5 rounded-lg mt-2 focus:outline-hidden focus:ring-2 focus:ring-indigo-100 focus:border-indigo-500 ${fieldErrors.businessSectorOther ? 'border-rose-400 ring-1 ring-rose-200' : 'border-gray-200'}`}
                  />
                  {fieldErrors.businessSectorOther && <p className="text-[10px] text-rose-600 mt-1">{fieldErrors.businessSectorOther}</p>}
                  </>
                )}
              </div>

              <div>
                <label className="block text-xs font-medium text-gray-500 uppercase mb-2">{t('intakeForm.business.requestedAmountLabel')}</label>
                <input
                  type="number"
                  step={1000}
                  min={5000}
                  {...(requestedAmountMax !== undefined ? { max: requestedAmountMax } : {})}
                  value={requestedAmount}
                  onChange={(e) => setRequestedAmount(Number(e.target.value))}
                  className="w-full text-sm font-bold border border-gray-200 p-2.5 rounded-lg focus:outline-hidden focus:ring-2 focus:ring-indigo-100 focus:border-indigo-500 text-indigo-600 font-mono"
                />
                <span className="text-[10px] text-gray-400 mt-1 block">
                  {benType === 'Group'
                    ? t('intakeForm.business.requestedAmountHintGroup')
                    : t('intakeForm.business.requestedAmountHint')}
                </span>
              </div>

              <div className="md:col-span-2">
                <label className="block text-xs font-medium text-gray-500 uppercase mb-2">{t('intakeForm.business.descriptionLabel')}</label>
                <textarea
                  rows={2}
                  value={businessDescription}
                  onChange={(e) => setBusinessDescription(e.target.value)}
                  placeholder={t('intakeForm.business.descriptionPlaceholder')}
                  className="w-full text-sm border border-gray-200 p-2.5 rounded-lg focus:outline-hidden focus:ring-2 focus:ring-indigo-100 focus:border-indigo-500"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-gray-500 uppercase mb-2">{t('intakeForm.business.expectedRevenueLabel')}</label>
                <input
                  type="number"
                  min={1000}
                  step={500}
                  value={expectedRevenue}
                  onChange={(e) => setExpectedRevenue(Number(e.target.value))}
                  className="w-full text-sm border border-gray-200 p-2.5 rounded-lg focus:outline-hidden focus:ring-2 focus:ring-indigo-100 focus:border-indigo-500 text-emerald-600 font-semibold"
                />
                <span className="text-[10px] text-gray-400 mt-1 block">{t('intakeForm.business.expectedRevenueHint')}</span>
              </div>
            </div>
            </div>
          </section>

          {/* Section 4: Proof of Business Establishment & Geo-Tagging */}
          <section className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
            <div className="bg-gradient-to-r from-emerald-700 to-emerald-800 px-5 py-3 flex items-center gap-3 border-l-4 border-emerald-300">
              <div className="w-9 h-9 rounded-lg bg-white/10 border border-white/20 flex items-center justify-center backdrop-blur-sm shrink-0">
                <MapPin className="w-4 h-4 text-emerald-100" />
              </div>
              <div className="flex-1 min-w-0">
                <div className="text-[11px] font-bold uppercase tracking-widest text-emerald-200">{t('intakeForm.establishment.stepLabel')}</div>
                <h3 className="text-sm font-bold text-white tracking-tight">{t('intakeForm.establishment.title')}</h3>
              </div>
              <span className="hidden sm:flex items-center gap-1 text-[11px] uppercase tracking-wider text-white/70 font-semibold">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-300" /> {t('intakeForm.establishment.fieldEvidenceBadge')}
              </span>
            </div>
            <div className="p-5">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              {/* Geotagging GPS */}
              <div className="bg-slate-50 border border-gray-200 rounded-lg p-4 space-y-3">
                <label className="block text-xs font-bold text-gray-500 uppercase">{t('intakeForm.establishment.geotag.label')}</label>
                <p className="text-[11px] text-gray-500 leading-normal">
                  {t('intakeForm.establishment.geotag.description')}
                </p>

                <div className="flex gap-2 items-center bg-white border border-gray-100 p-2 rounded-lg">
                  <MapPin className="w-4 h-4 text-rose-500 shrink-0" />
                  <div className="flex-1 text-xs font-mono text-gray-700">
                    {establishmentGpsStatus === 'idle' ? (
                      <span className="text-gray-400">{t('intakeForm.establishment.geotag.notCaptured')}</span>
                    ) : establishmentGpsStatus === 'fetching' ? (
                      <span className="text-gray-400 animate-pulse">{t('intakeForm.establishment.geotag.querying')}</span>
                    ) : establishmentGpsStatus === 'success' ? (
                      <span className="text-emerald-700 font-bold font-mono">
                        {t('intakeForm.establishment.geotag.coordinates', { lat: establishmentLat, longitude: establishmentLng })}
                      </span>
                    ) : (
                      <span className="text-rose-600 font-semibold font-sans">{t('intakeForm.establishment.geotag.error')}</span>
                    )}
                  </div>

                  <button
                    type="button"
                    onClick={captureEstablishmentGPS}
                    className="p-1 px-3 bg-slate-100 hover:bg-slate-200 text-gray-800 text-[10px] font-bold uppercase tracking-wider rounded border transition-colors cursor-pointer"
                  >
                    {t('intakeForm.establishment.geotag.lockButton')}
                  </button>
                </div>
              </div>

              {/* Photo Proof */}
              <div className="bg-slate-50 border border-gray-200 rounded-lg p-4 space-y-3">
                <label className="block text-xs font-bold text-gray-500 uppercase">{t('intakeForm.establishment.photo.label')}</label>
                <p className="text-[11px] text-gray-500 leading-normal">
                  {t('intakeForm.establishment.photo.description')}
                </p>

                <label
                  className={`border border-dashed border-gray-300 bg-white rounded-lg p-5 text-center flex flex-col items-center justify-center transition-colors relative ${
                    establishmentUploading ? 'opacity-60 cursor-wait' : 'hover:bg-gray-50 cursor-pointer'
                  }`}
                >
                  {establishmentUploading ? (
                    <>
                      <Loader2 className="w-5 h-5 text-[#115e59] mb-1.5 animate-spin" />
                      <span className="text-[11px] font-bold text-[#115e59] uppercase tracking-wide">{t('intakeForm.establishment.photo.uploading')}</span>
                      <span className="text-[11px] text-gray-400 mt-0.5">{t('intakeForm.establishment.photo.uploadingSubtext')}</span>
                    </>
                  ) : (
                    <>
                      <Camera className="w-5 h-5 text-gray-400 mb-1.5" />
                      <span className="text-[11px] font-bold text-[#115e59] uppercase tracking-wide">{t('intakeForm.establishment.photo.uploadButton')}</span>
                      <span className="text-[11px] text-gray-400 mt-0.5">{t('intakeForm.establishment.photo.maxSize')}</span>
                    </>
                  )}
                  <input
                    type="file"
                    accept="image/jpeg,image/jpg,image/png"
                    disabled={establishmentUploading}
                    onChange={handleEstablishmentFileChange}
                    className="hidden"
                  />
                </label>

                {establishmentUploadError && (
                  <div className="mt-2 text-[10px] text-rose-700 bg-rose-50 border border-rose-100 rounded px-2 py-1">
                    {t('intakeForm.establishment.photo.uploadFailed', { error: establishmentUploadError })}
                  </div>
                )}

                {establishmentPhoto && (
                  <div className="mt-2 flex items-center gap-2 bg-white p-1.5 rounded border border-gray-200">
                    <img
                      src={establishmentPhoto}
                      alt="Establishment proof preview"
                      className="w-10 h-10 object-cover rounded border border-gray-300 shadow-2xs"
                      referrerPolicy="no-referrer"
                    />
                    <div className="flex-1 text-[11px] truncate">
                      <span className="font-bold text-[#115e59] block">{t('intakeForm.establishment.photo.attachedLabel')}</span>
                      <button
                        type="button"
                        onClick={() => setEstablishmentPhoto('')}
                        className="text-red-500 font-bold hover:underline"
                      >
                        {t('intakeForm.establishment.photo.removeButton')}
                      </button>
                    </div>
                  </div>
                )}
              </div>
            </div>
            </div>
          </section>

          {/* Section 5: Guarantor / Co-Applicant Details */}
          <section className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
            <div className="bg-gradient-to-r from-violet-700 to-violet-800 px-5 py-3 flex items-center gap-3 border-l-4 border-violet-300">
              <div className="w-9 h-9 rounded-lg bg-white/10 border border-white/20 flex items-center justify-center backdrop-blur-sm shrink-0">
                <UserRoundCheck className="w-4 h-4 text-violet-100" />
              </div>
              <div className="flex-1 min-w-0">
                <div className="text-[11px] font-bold uppercase tracking-widest text-violet-200">{t('intakeForm.guarantor.badge')}</div>
                <h3 className="text-sm font-bold text-white tracking-tight">{t('intakeForm.guarantor.title')}</h3>
              </div>
              <span className="hidden sm:flex items-center gap-1 text-[11px] uppercase tracking-wider text-white/70 font-semibold">
                <span className="w-1.5 h-1.5 rounded-full bg-violet-300" /> {t('intakeForm.guarantor.optionalBadge')}
              </span>
            </div>
            <div className="p-5">
              <p className="text-[11px] text-gray-500 mb-4 leading-normal">
                {t('intakeForm.guarantor.description')}
              </p>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                <div>
                  <label className="block text-xs font-medium text-gray-500 uppercase mb-2">{t('intakeForm.guarantor.nameLabel')}</label>
                  <input
                    type="text"
                    value={guarantorName}
                    onChange={(e) => setGuarantorName(e.target.value)}
                    placeholder={t('intakeForm.guarantor.namePlaceholder')}
                    className="w-full text-sm border border-gray-200 p-2.5 rounded-lg focus:outline-hidden focus:ring-2 focus:ring-indigo-100 focus:border-indigo-500"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-500 uppercase mb-2">{t('intakeForm.guarantor.relationshipLabel')}</label>
                  <input
                    type="text"
                    value={guarantorRelationship}
                    onChange={(e) => setGuarantorRelationship(e.target.value)}
                    placeholder={t('intakeForm.guarantor.relationshipPlaceholder')}
                    className="w-full text-sm border border-gray-200 p-2.5 rounded-lg focus:outline-hidden focus:ring-2 focus:ring-indigo-100 focus:border-indigo-500"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-500 uppercase mb-2">{t('intakeForm.guarantor.contactLabel')}</label>
                  <input
                    type="tel"
                    pattern="[0-9]{10}"
                    value={guarantorContact}
                    onChange={(e) => setGuarantorContact(e.target.value)}
                    placeholder={t('intakeForm.guarantor.contactPlaceholder')}
                    className="w-full text-sm border border-gray-200 p-2.5 rounded-lg focus:outline-hidden focus:ring-2 focus:ring-indigo-100 focus:border-indigo-500"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-500 uppercase mb-2">{t('intakeForm.guarantor.idProofLabel')}</label>
                  <input
                    type="text"
                    value={guarantorIdProof}
                    onChange={(e) => setGuarantorIdProof(e.target.value)}
                    placeholder={t('intakeForm.guarantor.idProofPlaceholder')}
                    className="w-full text-sm border border-gray-200 p-2.5 rounded-lg focus:outline-hidden focus:ring-2 focus:ring-indigo-100 focus:border-indigo-500"
                  />
                </div>
                <div className="md:col-span-2">
                  <label className="block text-xs font-medium text-gray-500 uppercase mb-2">{t('intakeForm.guarantor.addressLabel')}</label>
                  <input
                    type="text"
                    value={guarantorAddress}
                    onChange={(e) => setGuarantorAddress(e.target.value)}
                    placeholder={t('intakeForm.guarantor.addressPlaceholder')}
                    className="w-full text-sm border border-gray-200 p-2.5 rounded-lg focus:outline-hidden focus:ring-2 focus:ring-indigo-100 focus:border-indigo-500"
                  />
                </div>
              </div>
            </div>
          </section>

          {/* Action Footer — secure submission */}
          <section className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
            <div className="px-5 py-4 flex flex-col sm:flex-row sm:items-center gap-4">
              <div className="flex items-center gap-3 flex-1 min-w-0">
                <div className="w-10 h-10 rounded-lg bg-emerald-50 border border-emerald-100 flex items-center justify-center shrink-0">
                  <Lock className="w-4 h-4 text-emerald-700" />
                </div>
                <div className="min-w-0">
                  <div className="text-[11px] font-bold text-[#115e59] tracking-tight">{t('intakeForm.footer.title')}</div>
                  <div className="text-[10px] text-gray-500 mt-0.5">{t('intakeForm.footer.subtitle')}</div>
                </div>
              </div>
              <div className="flex items-center gap-2 sm:gap-3 sm:shrink-0">
                <button
                  type="button"
                  onClick={() => {
                    if (confirm(t('alerts.discardConfirm'))) {
                      setActiveTab('tracking');
                    }
                  }}
                  className="text-gray-600 hover:text-gray-900 hover:bg-gray-50 text-[11px] font-bold px-4 py-2.5 rounded-lg cursor-pointer uppercase tracking-wider border border-gray-200 transition-colors"
                >
                  {t('intakeForm.footer.discardButton')}
                </button>
                <button
                  type="submit"
                  disabled={submitting || establishmentUploading}
                  className="bg-[#115e59] hover:bg-[#0f766e] disabled:opacity-60 disabled:cursor-wait text-white font-bold text-[11px] py-2.5 px-5 rounded-lg shadow-sm flex items-center gap-2 cursor-pointer transition-all uppercase tracking-wider border-b-2 border-[#0284c7]"
                  id="submit_beneficiary_registration_btn"
                >
                  {establishmentUploading || submitting ? (
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  ) : (
                    <ShieldCheck className="w-3.5 h-3.5" />
                  )}
                  {establishmentUploading
                    ? t('intakeForm.footer.waitingUpload')
                    : submitting
                      ? t('intakeForm.footer.saving')
                      : t('intakeForm.footer.submitButton')}
                </button>
              </div>
            </div>
          </section>
        </form>
      ) : activeTab === 'welfare' ? (
        <WelfareSchemes
          beneficiaries={beneficiaries}
          onAddBeneficiary={onAddBeneficiary}
          onUpdateBeneficiary={onUpdateBeneficiary}
          loggedBy={agentDisplayName}
        />
      ) : (
        /* Status Tracker & Verification Workspace */
        <div className="space-y-4" id="agent_tracker_workspace">
          {/* Section banner */}
          <div className="bg-gradient-to-r from-[#115e59] to-[#0f766e] p-4 rounded-xl flex flex-col md:flex-row md:items-center justify-between gap-3 shadow-md border-l-4 border-[#0284c7]">
            <div>
              <h4 className="font-bold text-white text-xs uppercase tracking-wide">{t('tracker.bannerTitle')}</h4>
              <p className="text-[11px] text-white/70 mt-0.5">{t('tracker.bannerSubtitle')}</p>
            </div>
            <div className="flex gap-2">
              <span className="inline-flex items-center gap-1.5 text-[10px] bg-white/10 text-white font-bold px-2.5 py-1 rounded-full border border-white/20 uppercase tracking-wider shadow-xs">
                <span className="w-1.5 h-1.5 rounded-full bg-[#0284c7] animate-pulse"></span>
                {t('tracker.activeSessionBadge')}
              </span>
            </div>
          </div>

          {/* Beneficiaries tracker list */}
          <div className="bg-white rounded-xl border border-gray-200 shadow-card overflow-hidden" id="tracker_table_card">
            <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse min-w-[720px]" id="agent_cases_table">
              <thead>
                <tr className="bg-gradient-to-r from-[#115e59] to-[#0f766e] text-white text-[10px] font-bold uppercase tracking-wider border-b-2 border-[#0284c7]">
                  <th className="p-3 px-3.5">{t('tracker.table.beneficiaryDisease')}</th>
                  <th className="p-3 px-3.5">{t('tracker.table.businessPlanSector')}</th>
                  <th className="p-3 px-3.5">{t('tracker.table.amountRequested')}</th>
                  <th className="p-3 px-3.5">{t('tracker.table.currentStatus')}</th>
                  <th className="p-3 px-3.5 text-center">{t('tracker.table.actionsRecovery')}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 text-xs">
                {beneficiaries.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="p-8 text-center text-gray-400">
                      {t('tracker.emptyState')}
                    </td>
                  </tr>
                ) : (
                  beneficiaries.map((b) => (
                    <tr key={b.id} className="hover:bg-sky-50/30 hover:shadow-xs transition-all" id={`row_ben_${b.id}`}>
                      {/* Name / Diagnosis */}
                      <td className="p-3 px-3.5">
                        <div className="font-bold text-gray-900 text-xs">{b.name}</div>
                        <div className="text-[11px] text-gray-400 mt-0.5">{t('tracker.idLabel')} <span className="font-mono">{b.id}</span></div>
                        <div className="flex items-center gap-1 mt-1.5">
                          <span className="text-[11px] bg-slate-100 rounded-full px-2 py-0.5 text-gray-600 font-bold">{getTypeLabel(b.type)}</span>
                          <span className={`text-[11px] font-bold px-2 py-0.5 rounded-full ${
                            b.diseaseType === 'Leprosy' ? 'bg-rose-50 text-rose-700' : b.diseaseType === 'HIV/AIDS' ? 'bg-violet-50 text-violet-700' : 'bg-amber-50 text-amber-700'
                          }`}>
                            {getDiseaseLabel(b.diseaseType)} ({getTreatmentLabel(b.treatmentStatus)})
                          </span>
                        </div>
                      </td>
                      {/* Business name */}
                      <td className="p-3 px-3.5">
                        <div className="font-bold text-[#171717] text-xs">{b.businessName}</div>
                        <div className="text-[10px] text-gray-500 italic mt-0.5">{b.businessSector}</div>

                        {/* Display Proof of Business Establishment details if logged at registration */}
                        {b.businessEstablishmentPhotoUrl ? (
                          <div className="mt-2 flex items-center gap-2 bg-slate-50 p-1.5 rounded-lg border border-gray-150 shadow-xs max-w-[240px]">
                            <img
                              src={b.businessEstablishmentPhotoUrl}
                              alt="Establishment proof preview"
                              className="w-8 h-8 object-cover rounded-md ring-1 ring-gray-200 shrink-0"
                              referrerPolicy="no-referrer"
                            />
                            <div className="text-[11px] text-gray-600 leading-tight">
                              <span className="font-bold text-[#115e59] block text-[10px]">{t('tracker.establishmentProofLabel')}</span>
                              {b.establishmentLatitude && (
                                <span className="font-mono text-gray-500 flex items-center gap-0.5 mt-0.5">
                                  <MapPin className="w-2.5 h-2.5 text-rose-500 inline" />
                                  {b.establishmentLatitude}, {b.establishmentLongitude}
                                </span>
                              )}
                            </div>
                          </div>
                        ) : (
                          <div className="text-[11px] text-gray-400 mt-1 italic flex items-center gap-1 bg-slate-50 p-1.5 rounded-lg max-w-[240px]">
                            <HelpCircle className="w-3 h-3 text-gray-400" />
                            {t('tracker.noEstablishmentPhoto')}
                          </div>
                        )}
                      </td>
                      {/* Financial info */}
                      <td className="p-3 px-3.5 font-mono font-bold text-gray-900">
                        ₹{(b.requestedAmount).toLocaleString('en-IN')}
                        {b.approvedAmount && (
                          <div className="text-[11px] text-emerald-700 font-bold mt-0.5">{t('tracker.approvedLabel', { amount: b.approvedAmount.toLocaleString('en-IN') })}</div>
                        )}
                      </td>
                      {/* Application Status */}
                      <td className="p-3 px-3.5">
                        {getStatusBadge(b.status)}
                      </td>
                      {/* Actions / Geo Verifications */}
                      <td className="p-3 px-3.5 text-center">
                        <div className="flex flex-col items-center gap-1.5 justify-center">
                          {/* 1. Verification Section */}
                          {b.status === 'Disbursed' ? (
                            <button
                              onClick={() => startVerificationProcess(b)}
                              className="inline-flex items-center gap-1 bg-[#115e59] hover:bg-[#0f766e] hover:shadow-md text-white text-[10px] uppercase tracking-wide font-bold px-2.5 py-1.5 rounded-full transition-all shadow-xs cursor-pointer border-b-2 border-[#0284c7] w-full max-w-[130px] justify-center"
                            >
                              <Camera className="w-3 h-3" />
                              {t('tracker.actions.verifyStartup')}
                            </button>
                          ) : b.status === 'Verified Active' ? (
                            <div className="inline-flex flex-col items-center">
                              <span className="inline-flex items-center gap-1 text-emerald-700 font-bold text-[10px] uppercase tracking-wide bg-emerald-50 px-2.5 py-1 rounded-full border border-emerald-100 shadow-xs">
                                <Check className="w-3 h-3" />
                                {t('tracker.actions.startupVerified')}
                              </span>
                              {b.verification?.latitude && (
                                <span className="text-[11px] text-gray-400 font-mono mt-0.5 flex items-center gap-0.5">
                                  <MapPin className="w-2.5 h-2.5 text-[#0284c7]" />
                                  {b.verification.latitude}, {b.verification.longitude}
                                </span>
                              )}
                            </div>
                          ) : (
                            <span className="text-gray-400 text-[10px]">{t('tracker.actions.awaitingApproval')}</span>
                          )}

                          {/* 2. Recovery / Repayments Section */}
                          {(b.status === 'Disbursed' || b.status === 'Verified Active') && (
                            <button
                              onClick={() => {
                                setSelectedRecoveryBenId(b.id);
                                const nextUnpaid = (b.emiSchedule ?? []).find(s => s.status !== 'Paid');
                                setRecoveryInstallmentIndex(nextUnpaid ? nextUnpaid.index : 1);
                                setRecoveryAmount(nextUnpaid ? nextUnpaid.promisedAmount - nextUnpaid.amountPaid : 0);
                                setRecoveryReceiptNumber(`RCP-${Math.floor(10000 + Math.random() * 90000)}`);
                              }}
                              className="inline-flex items-center gap-1 bg-emerald-600 hover:bg-emerald-700 hover:shadow-md text-white text-[10px] uppercase tracking-wide font-bold px-2.5 py-1.5 rounded-full transition-all shadow-xs cursor-pointer border-b-2 border-emerald-800 w-full max-w-[130px] justify-center"
                            >
                              <Banknote className="w-3.5 h-3.5" />
                              {t('tracker.actions.collectRecovery')}
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
            </div>
          </div>

          {/* Verification Multi-Step Form Modal Layer */}
          {selectedVerificationId && (
            <div className="fixed inset-0 bg-slate-900/40 backdrop-blur-xs flex items-center justify-center p-4 z-50 animate-fade-in" id="verification_flow_modal">
              <div className="bg-white rounded-lg shadow-card border border-gray-200 max-w-2xl w-full overflow-hidden">
                <div className="p-3 bg-[#115e59] text-white flex justify-between items-center border-b-2 border-[#0284c7]">
                  <div className="flex items-center gap-2">
                    <Compass className="w-4 h-4 text-[#0284c7]" />
                    <h3 className="font-bold text-xs uppercase tracking-wider text-white">{t('verificationModal.title')}</h3>
                  </div>
                  <button 
                    onClick={() => setSelectedVerificationId(null)}
                    className="text-white hover:text-red-400"
                  >
                    <Trash2 className="w-4 h-4 cursor-pointer" />
                  </button>
                </div>

                <form onSubmit={handleDisbursementVerificationSubmit} className="p-6 space-y-6">
                  <div className="bg-sky-50 text-sky-800 p-3 rounded-lg text-xs flex items-start gap-2 border border-sky-100">
                    <CheckCircle className="w-4 h-4 text-sky-600 shrink-0 mt-0.5" />
                    <span>
                      {t('verificationModal.sopNoticePrefix')} <b>{t('verificationModal.sopNoticeGeotag')}</b> {t('verificationModal.sopNoticeMiddle')} <b>{t('verificationModal.sopNoticePhoto')}</b> {t('verificationModal.sopNoticeSuffix')}
                    </span>
                  </div>

                  <div className="space-y-4">
                    {/* Geolocation Coordinate Capture */}
                    <div>
                      <label className="block text-xs font-semibold text-gray-500 uppercase mb-2">{t('verificationModal.geoStepLabel')}</label>
                      <div className="flex gap-2 items-center bg-slate-50 border border-gray-100 p-3 rounded-lg">
                        <MapPin className="w-5 h-5 text-rose-500 shrink-0" />

                        <div className="flex-1 text-xs">
                          {gpsStatus === 'idle' ? (
                            <span className="text-gray-500">{t('verificationModal.geoAwaiting')}</span>
                          ) : gpsStatus === 'fetching' ? (
                            <span className="text-gray-500">{t('verificationModal.geoRequesting')}</span>
                          ) : gpsStatus === 'success' ? (
                            <div>
                              <span className="font-semibold text-gray-800 font-mono">{t('verificationModal.geoLocked', { lat: gpsCoordinates.lat, longitude: gpsCoordinates.lng })}</span>
                              <span className="block text-[10px] text-emerald-600 mt-0.5 font-medium">✓ {t('verificationModal.geoLockedSubtext')}</span>
                            </div>
                          ) : (
                            <span className="text-rose-600 font-medium">{t('verificationModal.geoFailed')}</span>
                          )}
                        </div>

                        <button
                          type="button"
                          onClick={captureGPSCoordinates}
                          className="bg-white hover:bg-gray-100 text-gray-700 text-xs font-semibold border px-3 py-1.5 rounded cursor-pointer transition-colors"
                        >
                          {t('verificationModal.refreshGpsButton')}
                        </button>
                      </div>
                    </div>

                    {/* Photo upload and select */}
                    <div>
                      <label className="block text-xs font-semibold text-gray-500 uppercase mb-2">{t('verificationModal.photoStepLabel')}</label>

                      <div className="border border-dashed border-gray-200 rounded-lg p-4 flex flex-col items-center justify-center bg-slate-50">
                        <Camera className="w-8 h-8 text-gray-300 stroke-1 mb-2" />
                        <span className="text-xs text-gray-500 text-center block mb-3">{t('verificationModal.uploadPrompt')}</span>
                        <input
                          type="file"
                          accept="image/*"
                          onChange={handleFileChange}
                          className="hidden"
                          id="camera-photo-upload"
                        />
                        <label
                          htmlFor="camera-photo-upload"
                          className="bg-teal-800 hover:bg-teal-900 text-white font-semibold text-xs px-3 py-2 rounded shadow-2xs cursor-pointer transition-colors block text-center"
                        >
                          {t('verificationModal.selectMediaButton')}
                        </label>
                      </div>

                      {/* Preview */}
                      {verificationPhoto && (
                        <div className="mt-4 p-3 bg-slate-50 rounded-lg border border-gray-100 flex items-center gap-3">
                          <img 
                            src={verificationPhoto} 
                            alt="Validation Preview" 
                            className="w-16 h-16 object-cover rounded-lg border border-gray-200 shadow-2xs" 
                            referrerPolicy="no-referrer"
                          />
                          <div>
                            <span className="text-xs font-semibold text-gray-800 block">{t('verificationModal.previewLoaded')}</span>
                            <span className="text-[10px] text-emerald-600 block mt-0.5 font-semibold">✓ {t('verificationModal.previewReady')}</span>
                            <button
                              type="button"
                              onClick={() => setVerificationPhoto('')}
                              className="text-rose-600 hover:text-red-700 hover:underline text-[10px] font-semibold mt-1 block"
                            >
                              {t('verificationModal.removeFileButton')}
                            </button>
                          </div>
                        </div>
                      )}
                    </div>

                    {/* Custom note */}
                    <div>
                      <label className="block text-xs font-medium text-gray-500 uppercase mb-2">{t('verificationModal.remarkStepLabel')}</label>
                      <textarea
                        required
                        rows={2}
                        value={verificationComment}
                        onChange={(e) => setVerificationComment(e.target.value)}
                        placeholder={t('verificationModal.remarkPlaceholder')}
                        className="w-full text-sm border border-gray-200 p-2.5 rounded-lg focus:outline-hidden focus:ring-2 focus:ring-indigo-100 focus:border-indigo-500"
                      />
                    </div>
                  </div>

                  <div className="flex justify-end gap-3 pt-4 border-t border-gray-100">
                    <button
                      type="button"
                      onClick={() => setSelectedVerificationId(null)}
                      className="text-xs text-slate-500 font-semibold px-4 py-2 cursor-pointer"
                    >
                      {t('verificationModal.cancelButton')}
                    </button>
                    <button
                      type="submit"
                      disabled={!verificationPhoto && !verificationComment}
                      className="bg-emerald-600 hover:bg-emerald-700 disabled:opacity-50 text-white font-semibold text-xs py-2 px-5 rounded-lg cursor-pointer transition-colors"
                      id="save_startup_verification_btn"
                    >
                      {t('verificationModal.submitButton')}
                    </button>
                  </div>
                </form>
              </div>
            </div>
          )}

          {/* Collect Recovery Payment Form Modal Layer */}
          {selectedRecoveryBenId && (
            <div className="fixed inset-0 bg-slate-900/40 backdrop-blur-xs flex items-center justify-center p-4 z-50 animate-fade-in" id="recovery_collection_modal">
              <div className="bg-white rounded-lg shadow-card border border-gray-200 max-w-2xl w-full overflow-hidden">
                <div className="p-3 bg-emerald-800 text-white flex justify-between items-center border-b-2 border-emerald-900">
                  <div className="flex items-center gap-2">
                    <Banknote className="w-4 h-4 text-emerald-100" />
                    <h3 className="font-bold text-xs uppercase tracking-wider text-white">{t('recoveryModal.title')}</h3>
                  </div>
                  <button 
                    onClick={() => setSelectedRecoveryBenId(null)}
                    className="text-white hover:text-red-350"
                  >
                    <Plus className="w-5 h-5 cursor-pointer rotate-45" />
                  </button>
                </div>

                <form onSubmit={handleCollectRecoverySubmit} className="p-6 space-y-4">
                  <div className="bg-emerald-50 text-emerald-800 p-3 rounded-lg text-xs flex items-start gap-2 border border-emerald-100 animate-fade-in">
                    <ShieldCheck className="w-4 h-4 text-emerald-600 shrink-0 mt-0.5" />
                    <div>
                      <span className="font-bold">{t('recoveryModal.policyTitle')}</span>
                      <p className="mt-0.5 text-[11px] leading-normal text-emerald-700">
                        {t('recoveryModal.policyTextPrefix')} <b>{t('recoveryModal.policyTextBold')}</b>, {t('recoveryModal.policyTextSuffix')}
                      </p>
                    </div>
                  </div>

                  {/* Beneficiary Name Banner inside Form */}
                  <div className="p-3 bg-slate-50 rounded-lg border border-gray-150">
                    <span className="text-[10px] text-gray-400 uppercase font-bold block">{t('recoveryModal.collectingForLabel')}</span>
                    <span className="text-sm font-bold text-[#115e59]">
                      {beneficiaries.find(b => b.id === selectedRecoveryBenId)?.name}
                    </span>
                    <span className="text-xs text-gray-500 block mt-0.5">
                      {t('recoveryModal.enterpriseLabel')} <span className="font-semibold text-gray-700">{beneficiaries.find(b => b.id === selectedRecoveryBenId)?.businessName}</span>
                    </span>
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {/* Select installment index */}
                    <div>
                      <label className="block text-xs font-semibold text-gray-500 uppercase mb-2">{t('recoveryModal.installmentLabel')}</label>
                      <select
                        value={recoveryInstallmentIndex}
                        onChange={(e) => {
                          const idx = Number(e.target.value);
                          setRecoveryInstallmentIndex(idx);
                          // Suggest suggested EMI amount
                          const ben = beneficiaries.find(b => b.id === selectedRecoveryBenId);
                          const matchingEMI = (ben?.emiSchedule ?? []).find(s => s.index === idx);
                          if (matchingEMI) {
                            setRecoveryAmount(matchingEMI.promisedAmount - matchingEMI.amountPaid);
                          }
                        }}
                        className="w-full text-sm border border-gray-200 p-2.5 rounded-lg focus:outline-hidden focus:ring-2 focus:ring-indigo-100 focus:border-indigo-500 bg-white"
                      >
                        {(beneficiaries.find(b => b.id === selectedRecoveryBenId)?.emiSchedule ?? []).map((sch) => (
                          <option key={sch.index} value={sch.index}>
                            {t('recoveryModal.installmentOption', { index: sch.index, dueDate: sch.dueDate, promised: sch.promisedAmount, paid: sch.amountPaid })}
                          </option>
                        ))}
                      </select>
                    </div>

                    {/* Recovery Amount Collected */}
                    <div>
                      <label className="block text-xs font-semibold text-gray-500 uppercase mb-2">{t('recoveryModal.amountLabel')}</label>
                      <input
                        type="number"
                        required
                        min={1}
                        value={recoveryAmount}
                        onChange={(e) => setRecoveryAmount(Number(e.target.value))}
                        className="w-full text-sm font-bold border border-gray-200 p-2.5 rounded-lg focus:outline-hidden focus:ring-2 focus:ring-indigo-100 focus:border-indigo-500 text-emerald-600 font-mono"
                      />
                    </div>

                    {/* Receipt Number */}
                    <div>
                      <label className="block text-xs font-semibold text-gray-500 uppercase mb-2">{t('recoveryModal.receiptLabel')}</label>
                      <input
                        type="text"
                        required
                        value={recoveryReceiptNumber}
                        onChange={(e) => setRecoveryReceiptNumber(e.target.value)}
                        placeholder={t('recoveryModal.receiptPlaceholder')}
                        className="w-full text-sm font-mono border border-gray-200 p-2.5 rounded-lg focus:outline-hidden focus:ring-2 focus:ring-indigo-100 focus:border-indigo-500"
                      />
                    </div>

                    {/* JPG Proof Attachment upload */}
                    <div>
                      <label className="block text-xs font-semibold text-gray-500 uppercase mb-2">{t('recoveryModal.proofUploadLabel')}</label>
                      <label className="border border-dashed border-gray-300 bg-slate-50 hover:bg-slate-100 rounded-lg p-2 flex flex-col items-center justify-center cursor-pointer transition-colors">
                        <Upload className="w-4 h-4 text-gray-450 mb-1" />
                        <span className="text-[11px] font-bold text-gray-600 uppercase tracking-wide">{t('recoveryModal.attachButton')}</span>
                        <input
                          type="file"
                          accept="image/jpeg,image/jpg"
                          onChange={handleRecoveryFileChange}
                          className="hidden"
                        />
                      </label>
                    </div>
                  </div>

                  {/* Receipt Proof Photo Preview */}
                  {recoveryProofPhoto && (
                    <div className="p-3 bg-slate-50 rounded-lg border border-gray-150 flex items-center gap-3 animate-fade-in">
                      <img 
                        src={recoveryProofPhoto} 
                        alt="SOP Receipt Preview" 
                        className="w-16 h-16 object-cover rounded-md border border-gray-300 shadow-2xs shrink-0" 
                        referrerPolicy="no-referrer"
                      />
                      <div>
                        <span className="text-xs font-semibold text-emerald-800 block">{t('recoveryModal.proofAttachedLabel')}</span>
                        <span className="text-[10px] text-gray-400 block mt-0.5">{t('recoveryModal.proofValidatedText')}</span>
                        <button
                          type="button"
                          onClick={() => setRecoveryProofPhoto('')}
                          className="text-red-500 font-bold text-[10px] hover:underline hover:text-red-700 mt-1 block"
                        >
                          {t('recoveryModal.removeProofButton')}
                        </button>
                      </div>
                    </div>
                  )}

                  {/* Notes */}
                  <div>
                    <label className="block text-xs font-semibold text-gray-500 uppercase mb-2">{t('recoveryModal.notesLabel')}</label>
                    <textarea
                      rows={2}
                      value={recoveryNote}
                      onChange={(e) => setRecoveryNote(e.target.value)}
                      placeholder={t('recoveryModal.notesPlaceholder')}
                      className="w-full text-sm border border-gray-200 p-2.5 rounded-lg focus:outline-hidden focus:ring-2 focus:ring-indigo-100 focus:border-indigo-500"
                    />
                  </div>

                  <div className="flex justify-end gap-3 pt-4 border-t border-gray-200">
                    <button
                      type="button"
                      onClick={() => setSelectedRecoveryBenId(null)}
                      className="text-xs text-slate-500 font-semibold px-4 py-2 cursor-pointer"
                    >
                      {t('recoveryModal.cancelButton')}
                    </button>
                    <button
                      type="submit"
                      disabled={!recoveryAmount || !recoveryReceiptNumber || !recoveryProofPhoto}
                      className="bg-emerald-600 hover:bg-emerald-700 disabled:opacity-50 text-white font-bold text-xs py-2 px-5 rounded cursor-pointer transition-colors uppercase tracking-wider border-b-2 border-emerald-800"
                    >
                      {t('recoveryModal.submitButton')}
                    </button>
                  </div>
                </form>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
