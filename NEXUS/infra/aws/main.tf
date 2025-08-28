terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.23"
    }
    helm = {
      source  = "hashicorp/helm"
      version = "~> 2.11"
    }
  }
  backend "s3" {
    bucket = "nexus-terraform-state"
    key    = "production/terraform.tfstate"
    region = "us-west-2"
  }
}

provider "aws" {
  region = var.aws_region
}

provider "kubernetes" {
  host                   = module.eks.cluster_endpoint
  cluster_ca_certificate = base64decode(module.eks.cluster_certificate_authority_data)
  token                  = data.aws_eks_cluster_auth.this.token
}

provider "helm" {
  kubernetes {
    host                   = module.eks.cluster_endpoint
    cluster_ca_certificate = base64decode(module.eks.cluster_certificate_authority_data)
    token                  = data.aws_eks_cluster_auth.this.token
  }
}

# Módulo EKS para el cluster Kubernetes
module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 19.0"

  cluster_name    = "nexus-production"
  cluster_version = "1.27"

  vpc_id     = module.vpc.vpc_id
  subnet_ids = module.vpc.private_subnets

  cluster_endpoint_public_access = true

  eks_managed_node_groups = {
    main = {
      min_size     = 3
      max_size     = 15
      desired_size = 5

      instance_types = ["m6a.2xlarge", "m6i.2xlarge"]
      capacity_type  = "SPOT"

      labels = {
        Environment = "production"
        NodeGroup   = "main"
      }
    }

    memory_optimized = {
      min_size     = 2
      max_size     = 8
      desired_size = 3

      instance_types = ["r6a.4xlarge"]
      capacity_type  = "SPOT"

      labels = {
        Environment = "production"
        NodeGroup   = "memory-optimized"
      }

      taints = [
        {
          key    = "memory-optimized"
          value  = "true"
          effect = "NO_SCHEDULE"
        }
      ]
    }
  }

  node_security_group_additional_rules = {
    ingress_allow_access_from_control_plane = {
      type                          = "ingress"
      protocol                      = "tcp"
      from_port                     = 1025
      to_port                       = 65535
      source_cluster_security_group = true
      description                   = "Allow traffic from control plane to workers"
    }
  }
}

# Módulo VPC para networking
module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.0"

  name = "nexus-vpc"
  cidr = "10.0.0.0/16"

  azs             = ["us-west-2a", "us-west-2b", "us-west-2c"]
  private_subnets = ["10.0.1.0/24", "10.0.2.0/24", "10.0.3.0/24"]
  public_subnets  = ["10.0.101.0/24", "10.0.102.0/24", "10.0.103.0/24"]

  enable_nat_gateway   = true
  single_nat_gateway   = false
  enable_dns_hostnames = true

  public_subnet_tags = {
    "kubernetes.io/role/elb" = 1
  }

  private_subnet_tags = {
    "kubernetes.io/role/internal-elb" = 1
  }
}

# Base de datos RDS para PostgreSQL con Apache AGE
resource "aws_db_instance" "nexus_postgres" {
  identifier              = "nexus-postgres-production"
  instance_class          = "db.r6g.4xlarge"
  allocated_storage       = 1000
  max_allocated_storage   = 2000
  engine                  = "postgres"
  engine_version          = "15.3"
  username                = var.db_username
  password                = var.db_password
  db_name                 = "nexus_production"
  multi_az                = true
  storage_type            = "gp3"
  storage_encrypted       = true
  backup_retention_period = 35
  skip_final_snapshot     = false
  deletion_protection     = true

  vpc_security_group_ids = [module.vpc.default_security_group_id]
  db_subnet_group_name   = aws_db_subnet_group.nexus.name

  performance_insights_enabled = true
  monitoring_interval          = 60

  parameter_group_name = aws_db_parameter_group.nexus.name

  tags = {
    Environment = "production"
    Application = "nexus"
  }
}

# Grupo de parámetros personalizados para PostgreSQL
resource "aws_db_parameter_group" "nexus" {
  name   = "nexus-postgres15-production"
  family = "postgres15"

  parameter {
    name  = "shared_preload_libraries"
    value = "age,pg_stat_statements"
  }

  parameter {
    name  = "max_connections"
    value = "500"
  }

  parameter {
    name  = "work_mem"
    value = "16MB"
  }

  parameter {
    name  = "maintenance_work_mem"
    value = "1GB"
  }
}

# Bucket S3 para almacenamiento
resource "aws_s3_bucket" "nexus_storage" {
  bucket = "nexus-production-storage"

  tags = {
    Environment = "production"
    Application = "nexus"
  }
}

resource "aws_s3_bucket_versioning" "nexus_storage" {
  bucket = aws_s3_bucket.nexus_storage.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "nexus_storage" {
  bucket = aws_s3_bucket.nexus_storage.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}