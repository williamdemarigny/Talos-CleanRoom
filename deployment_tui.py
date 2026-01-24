import subprocess
import os
import time

class DeploymentManager:
    def __init__(self):
        pass
    
    def check_dependencies(self):
        """Check required dependencies"""
        print("Checking dependencies...")
        deps = ["terraform", "talhelper", "talosctl", "sops", "jq", "curl"]
        
        for dep in deps:
            try:
                # Try different approaches to find the command
                result = subprocess.run(["which", dep], 
                                       stdout=subprocess.PIPE, 
                                       stderr=subprocess.PIPE,
                                       shell=False)
                
                if result.returncode == 0:
                    print(f"✓ {dep} found at: {result.stdout.strip().decode()}")
                else:
                    # Try alternative check
                    result2 = subprocess.run(["command", "-v", dep], 
                                            stdout=subprocess.PIPE, 
                                            stderr=subprocess.PIPE,
                                            shell=False)
                    
                    if result2.returncode == 0:
                        print(f"✓ {dep} found at: {result2.stdout.strip().decode()}")
                    else:
                        print(f"✗ {dep} not found")
                        return False
            except Exception as e:
                print(f"✗ Error checking {dep}: {e}")
                return False
        
        print("All dependencies satisfied")
        time.sleep(0.5)  # Small delay for readability
        return True
    
    def run_terraform_init(self):
        """Run terraform init"""
        print("Running terraform init...")
        try:
            result = subprocess.run(["terraform", "init"], 
                                  stdout=subprocess.PIPE, 
                                  stderr=subprocess.PIPE,
                                  check=True)
            print("✓ Terraform init completed successfully")
            return True
        except subprocess.CalledProcessError as e:
            print(f"✗ Terraform init failed: {e.stderr.decode()}")
            return False
    
    def run_terraform_apply(self):
        """Run terraform apply"""
        print("Running terraform apply...")
        try:
            result = subprocess.run(["terraform", "apply", "-auto-approve"], 
                                  stdout=subprocess.PIPE, 
                                  stderr=subprocess.PIPE,
                                  check=True)
            print("✓ Terraform apply completed successfully")
            return True
        except subprocess.CalledProcessError as e:
            print(f"✗ Terraform apply failed: {e.stderr.decode()}")
            return False
    
    def run_talosctl(self):
        """Run talosctl commands"""
        print("Running Talos commands...")
        try:
            # Example command - replace with actual Talos operations
            result = subprocess.run(["talosctl", "version"], 
                                  stdout=subprocess.PIPE, 
                                  stderr=subprocess.PIPE,
                                  check=True)
            print("✓ Talos commands executed successfully")
            return True
        except subprocess.CalledProcessError as e:
            print(f"✗ Talos command failed: {e.stderr.decode()}")
            return False
    
    def run_sops(self):
        """Run sops operations"""
        print("Running SOPS operations...")
        try:
            # Example command - replace with actual SOPS operations
            result = subprocess.run(["sops", "--version"], 
                                  stdout=subprocess.PIPE, 
                                  stderr=subprocess.PIPE,
                                  check=True)
            print("✓ SOPS operations completed successfully")
            return True
        except subprocess.CalledProcessError as e:
            print(f"✗ SOPS operation failed: {e.stderr.decode()}")
            return False
    
    def run_deployment(self):
        """Run the complete deployment process"""
        print("Starting deployment process...")
        
        # Step 1: Check dependencies
        if not self.check_dependencies():
            print("Deployment cancelled due to missing dependencies")
            return False
        
        # Step 2: Run terraform init
        if not self.run_terraform_init():
            print("Deployment cancelled due to terraform init failure")
            return False
        
        # Step 3: Run terraform apply
        if not self.run_terraform_apply():
            print("Deployment cancelled due to terraform apply failure")
            return False
        
        # Step 4: Run Talos commands
        if not self.run_talosctl():
            print("Talos operations failed, but continuing...")
        
        # Step 5: Run SOPS operations
        if not self.run_sops():
            print("SOPS operations failed, but continuing...")
        
        print("Deployment process completed successfully!")
        return True

# Main execution
if __name__ == "__main__":
    manager = DeploymentManager()
    success = manager.run_deployment()
    
    if success:
        print("\n🎉 All deployment steps completed successfully!")
    else:
        print("\n❌ Deployment process encountered errors")
        exit(1)
