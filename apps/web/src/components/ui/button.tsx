"use client";

import { Button as BaseButton } from "@base-ui/react/button";
import Link from "next/link";
import type { ComponentProps, ReactNode } from "react";

type Props = ComponentProps<typeof BaseButton> & {
  variant?: "primary" | "secondary" | "danger" | "ghost";
  children: ReactNode;
};

export function Button({ variant = "primary", className = "", children, ...props }: Props) {
  return <BaseButton className={`button button--${variant} ${className}`} {...props}>{children}</BaseButton>;
}

export function ButtonLink({ variant = "primary", className = "", children, ...props }: ComponentProps<typeof Link> & Pick<Props, "variant">) {
  return <Link className={`button button--${variant} ${className}`} {...props}>{children}</Link>;
}
