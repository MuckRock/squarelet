export interface User {
  id: number;
  uuid: string;
  username: string;
  name: string;
  avatar_url: string;
}

export type UserSelection = {
  type: "user";
  id: number;
  username: string;
  name: string;
  avatar_url: string;
};

export type EmailSelection = {
  type: "email";
  email: string;
  name: string;
  id: string;
};

export type Selection = UserSelection | EmailSelection;

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
  member_count: number;
}
