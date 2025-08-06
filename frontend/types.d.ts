export interface Organization {
  id: number;
  uuid: string;
  name: string;
  slug: string;
  max_users: boolean;
  individual: boolean;
  private: boolean;
  verified_journalist: boolean;
  updated_at: string | Date;
  payment_failed: boolean;
  avatar_url: string | URL;
  merged: Date | null;
}
