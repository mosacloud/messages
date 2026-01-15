import { useAuth } from "@/features/auth";
import { MainLayout } from "@/features/layouts/components/main";
import { MosaLoginPage } from "@/features/home";

export default function HomePage() {
  const { user } = useAuth();

  if (user) {
    return <MainLayout />;
  }

  return <MosaLoginPage />;
}
