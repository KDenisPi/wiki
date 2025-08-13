/**
 * @file test_props_match.cpp
 * @author Denis Kudia (dkudja@gmail.com)
 * @brief
 * @version 0.1
 * @date 2025-08-08
 *
 * @copyright Copyright (c) 2025
 *
 */

#include <stdlib.h>
#include <iostream>
#include <string>
#include "rapidjson/document.h"
#include "smallthings.h"

#define MAX_LINE_LENGTH 1024*1024*5 //5Mb

int main (int argc, char* argv[])
{
    int status = EXIT_FAILURE;
    if(argc < 3){
        std::cout << "File names are absent. app prop_dict.json item.json" << std::endl;
        exit(status);
    }

    char buffer[MAX_LINE_LENGTH]; // Declare a character array (buffer) to store the line

    int fd_prop = open(argv[1], O_RDONLY);
    if(fd_prop == -1){
        std::cout << "Error opening file " << argv[1] << std::endl; // Print an error message
        exit(status); // Exit the program with an error status
    }

    size_t b_read = b_read = read(fd_prop, buffer, MAX_LINE_LENGTH-1);
    if(b_read == -1){
        std::cout << "Error reading file " << argv[1] << std::endl; // Print an error message
    }
    else{
        buffer[b_read] = 0x00;

        rapidjson::Document d_prop;
        d_prop.Parse(buffer);
        if(d_prop.HasParseError()){
            auto err = d_prop.GetParseError();
            std::cout << argv[1] << " Parse error: " << std::to_string(err) << " Offset: " << d_prop.GetErrorOffset() << std::endl;
        }

        std::cout << argv[1] << " Props count: " << d_prop.MemberCount() << std::endl;

        // Open the properties file in read mode ("r")
        FILE *fp_prop = fopen(argv[2], "r");
        // Check if the file was opened successfully
        if (fp_prop == NULL) {
            std::cout << "Error reading file " << argv[1] << std::endl; // Print an error message
        }
        else{
            if(fgets(buffer, MAX_LINE_LENGTH, fp_prop) != NULL) {
                rapidjson::Document d_item;
                d_item.Parse(buffer);

                if(d_item.HasParseError()){
                    auto err = d_item.GetParseError();
                    std::cout << argv[2] << " Parse error: " << std::to_string(err) << " Offset: " << d_item.GetErrorOffset() << std::endl;
                }
                else{
                    auto v_claims = d_item.FindMember("claims");
                    if(v_claims != d_item.MemberEnd()){
                        std::cout << "Name: " << v_claims->name.GetString() << " Type: " << v_claims->value.GetType() << " Count: "
                            << v_claims->value.MemberCount() << std::endl;

                        for(auto cl_v = v_claims->value.MemberBegin(); cl_v != v_claims->value.MemberEnd(); ++cl_v){
                            auto prop = d_prop.FindMember(cl_v->name.GetString());
                            std::cout << "Name: " << cl_v->name.GetString() << " "
                                << (prop!=d_prop.MemberEnd() ? prop->value[0].GetString() : " Unknown ") << std::endl;
                        }
                    }
                    else
                        std::cout << "No such member: " << "claims" << std::endl;
                }
            }
            status = EXIT_SUCCESS;
        }

        fclose(fp_prop);
    }

    close(fd_prop);

    exit(status);
}