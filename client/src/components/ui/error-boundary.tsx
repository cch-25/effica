"use client";

import { Component, type ErrorInfo, type ReactNode } from "react";
import { StatePanel } from "./state-panel";

export class ErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch(error: Error, info: ErrorInfo) { console.error("UI boundary", error, info.componentStack); }
  render() { return this.state.failed ? <StatePanel state="fatal" onRetry={() => this.setState({ failed: false })} /> : this.props.children; }
}
