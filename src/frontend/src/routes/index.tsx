import { createFileRoute } from "@tanstack/react-router";

import { useAuth } from "@/features/auth";
import { MainLayout } from "@/features/layouts/components/main";
import { MosaLoginPage } from "@/features/home";

const HomePage = () => {
  const { user } = useAuth();

  if (user) {
    return <MainLayout />;
  }

  return <MosaLoginPage />;
};

export const Route = createFileRoute("/")({
  component: HomePage,
});
